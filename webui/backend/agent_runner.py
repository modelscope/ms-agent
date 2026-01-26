# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Agent runner for MS-Agent Web UI
Manages the execution of ms-agent through subprocess with log streaming.
"""
import asyncio
import os
import re
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional


class AgentRunner:
    """Runs ms-agent as a subprocess with output streaming"""

    def __init__(self,
                 session_id: str,
                 project: Dict[str, Any],
                 config_manager,
                 on_output: Callable[[Dict[str, Any]], None] = None,
                 on_log: Callable[[Dict[str, Any]], None] = None,
                 on_progress: Callable[[Dict[str, Any]], None] = None,
                 on_complete: Callable[[Dict[str, Any]], None] = None,
                 on_error: Callable[[Dict[str, Any]], None] = None):
        self.session_id = session_id
        self.project = project
        self.config_manager = config_manager
        self.on_output = on_output
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error

        self.process: Optional[asyncio.subprocess.Process] = None
        self.is_running = False
        self._accumulated_output = ''
        self._current_step = None
        self._workflow_steps = []
        self._stop_requested = False

        base_dir = Path(__file__).resolve().parents[
            1]  # equal to dirname(dirname(__file__))
        work_dir = base_dir / 'work_dir' / str(session_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir = work_dir

    async def start(self, query: str):
        self._stop_requested = False
        self.is_running = True
        sent_terminal_event = False

        try:
            cmd = self._build_command(query)
            env = self._build_env()

            if self.on_log:
                self.on_log({
                    'level': 'info',
                    'message': f'Starting agent: {" ".join(cmd[:5])}...',
                    'timestamp': datetime.now().isoformat()
                })

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.project['path'],
                start_new_session=True)

            read_exc = None
            try:
                await self._read_output()
            except Exception as e:
                # Do not terminate the workflow immediately when an exception occurs while reading output.
                # Record it first; later still wait and return the rc.
                read_exc = e
                if self.on_log:
                    self.on_log({
                        'level': 'error',
                        'message': f'Read output failed: {repr(e)}',
                        'timestamp': datetime.now().isoformat()
                    })

            rc = await self.process.wait()
            self.is_running = False

            if self._stop_requested:
                if self.on_error:
                    self.on_error({
                        'message': 'Stopped by user',
                        'returncode': rc
                    })
                    sent_terminal_event = True
                return

            if rc == 0:
                if self.on_complete:
                    self.on_complete({'returncode': 0})
                    sent_terminal_event = True
            else:
                # Non-zero must be returned.
                msg = f'Process exited with code: {rc}'
                if read_exc:
                    msg += f' (and output reader failed: {repr(read_exc)})'
                if self.on_error:
                    self.on_error({'message': msg, 'returncode': rc})
                    sent_terminal_event = True

        except Exception:
            self.is_running = False
            import traceback
            tb = traceback.format_exc()
            print(tb)
            if self.on_error:
                self.on_error({
                    'message': tb,
                    'type': 'startup_error',
                    'returncode': -1
                })
                sent_terminal_event = True

        finally:
            # Fallback: ensure the frontend always receives the completion signal under all circumstances.
            if not sent_terminal_event and self.on_error:
                self.on_error({
                    'message': 'Agent terminated unexpectedly',
                    'returncode': -1
                })

    async def stop(self):
        """Stop the agent"""
        self._stop_requested = True
        self.is_running = False
        if not self.process:
            return

        try:
            # If already exited, nothing to do
            if self.process.returncode is not None:
                return

            # Prefer terminating the whole process group to stop child processes too
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except Exception:
                # Fallback to terminating only the parent
                try:
                    self.process.terminate()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
        except Exception:
            pass

    async def send_input(self, text: str):
        """Send input to the agent"""
        if self.process and self.process.stdin:
            self.process.stdin.write((text + '\n').encode())
            await self.process.stdin.drain()

    def _build_command(self, query: str) -> list:
        """Build the command to run the agent"""
        project_type = self.project.get('type')
        project_path = self.project['path']
        config_file = self.project.get('config_file', '')

        # Get python executable
        python = sys.executable

        # Get MCP config file path
        mcp_file = self.config_manager.get_mcp_file_path()

        if project_type == 'workflow' or project_type == 'agent':
            # Use ms-agent CLI command (installed via entry point)
            cmd = [
                'ms-agent', 'run', '--config', config_file,
                '--trust_remote_code', 'true', '--output_dir', self.work_dir
            ]

            if query:
                cmd.extend(['--query', query])

            if os.path.exists(mcp_file):
                cmd.extend(['--mcp_server_file', mcp_file])

            # Add LLM config
            llm_config = self.config_manager.get_llm_config()
            if llm_config.get('api_key'):
                provider = llm_config.get('provider', 'modelscope')
                if provider == 'modelscope':
                    cmd.extend(['--modelscope_api_key', llm_config['api_key']])
                elif provider == 'openai':
                    cmd.extend(['--openai_api_key', llm_config['api_key']])

        elif project_type == 'script':
            # Run the script directly
            cmd = [python, self.project['config_file']]
        else:
            cmd = [python, '-m', 'ms_agent', 'run', '--config', project_path]

        return cmd

    def _build_env(self) -> Dict[str, str]:
        """Build environment variables"""
        env = os.environ.copy()

        # Add config env vars
        env.update(self.config_manager.get_env_vars())

        # Set PYTHONUNBUFFERED for real-time output
        env['PYTHONUNBUFFERED'] = '1'

        return env

    async def _read_output(self):
        """Read and process output from the subprocess (robust, no readline limit issue)"""
        print('[Runner] Starting to read output...')

        # Parameters related to reading output: can be adjusted as needed.
        CHUNK_SIZE = 4096
        # For single-line / no-newline output, buffer up to this size;
        # if it exceeds the limit, flush in slices to avoid memory blow-up.
        MAX_LINE_BUFFER = 256 * 1024

        buf = bytearray()
        return_code = None

        try:
            while self.is_running and self.process and self.process.stdout:
                chunk = await self.process.stdout.read(CHUNK_SIZE)
                if not chunk:
                    print('[Runner] No more output, breaking...')
                    break

                buf.extend(chunk)

                # Split out complete lines (delimited by '\n').
                while True:
                    nl = buf.find(b'\n')
                    if nl == -1:
                        # No newline but the buffer is too large:
                        # force-flush it as a "line" to _process_line to avoid unbounded growth.
                        if len(buf) >= MAX_LINE_BUFFER:
                            part = bytes(buf[:MAX_LINE_BUFFER])
                            del buf[:MAX_LINE_BUFFER]
                            text = part.decode(
                                'utf-8', errors='replace').rstrip()
                            print(f'[Runner] Output(partial): {text[:200]}'
                                  if len(text) > 200 else
                                  f'[Runner] Output(partial): {text}')
                            await self._process_line(text)
                        break

                    line_bytes = bytes(buf[:nl + 1])
                    del buf[:nl + 1]

                    text = line_bytes.decode(
                        'utf-8', errors='replace').rstrip()
                    print(f'[Runner] Output: {text[:200]}'
                          if len(text) > 200 else f'[Runner] Output: {text}')
                    await self._process_line(text)

            # Flush: the final tail chunk that doesn't end with a newline.
            if buf:
                text = bytes(buf).decode('utf-8', errors='replace').rstrip()
                print(f'[Runner] Output(tail): {text[:200]}'
                      if len(text) > 200 else f'[Runner] Output(tail): {text}')
                await self._process_line(text)
                buf.clear()

        except Exception as e:
            # Note: do not end the entire workflow just because of an exception while reading output;
            # still call wait to obtain the exit code and return it.
            print(f'[Runner] Read error: {e}')
            import traceback
            traceback.print_exc()

            # Record the output-reading error as a log/error message first,
            # but ultimately rely on the process exit code (if available).
            if not self._stop_requested and self.on_error:
                self.on_error({'message': str(e), 'type': 'read_error'})

        finally:
            # Always call wait no matter what, to ensure the exit code is returned to the frontend
            # (preventing it from loading indefinitely).
            try:
                if self.process:
                    return_code = await self.process.wait()
                    print(f'[Runner] Process exited with code: {return_code}')

                    if self._stop_requested:
                        if self.on_log:
                            self.on_log({
                                'level': 'info',
                                'message': 'Agent stopped by user',
                                'timestamp': datetime.now().isoformat()
                            })
                    else:
                        if return_code == 0:
                            if self.on_complete:
                                self.on_complete({
                                    'status': 'success',
                                    'message': 'Agent completed successfully',
                                    'code': 0
                                })
                        else:
                            # Key: if the code is non-zero, it must be returned (error code)
                            # so the frontend can reach a terminal state.
                            if self.on_error:
                                self.on_error({
                                    'message':
                                    f'Agent exited with code {return_code}',
                                    'type': 'exit_error',
                                    'code': return_code
                                })
            except Exception as e:
                print(f'[Runner] Wait/Finalize error: {e}')
                import traceback
                traceback.print_exc()
                if not self._stop_requested and self.on_error:
                    # Provide a fallback error code if `wait` fails as well.
                    self.on_error({
                        'message': str(e),
                        'type': 'finalize_error',
                        'code': -1
                    })
            finally:
                self.is_running = False
                print('[Runner] Finished reading output')

    async def _process_line(self, line: str):
        """Process a line of output"""
        # Log the line
        if self.on_log:
            log_level = self._detect_log_level(line)
            await self.on_log({
                'level': log_level,
                'message': line,
                'timestamp': datetime.now().isoformat()
            })

        # Parse for special patterns
        await self._detect_patterns(line)

    def _detect_log_level(self, line: str) -> str:
        """Detect log level from line"""
        line_lower = line.lower()
        if '[error' in line_lower or 'error:' in line_lower:
            return 'error'
        elif '[warn' in line_lower or 'warning:' in line_lower:
            return 'warning'
        elif '[debug' in line_lower:
            return 'debug'
        return 'info'

    async def _detect_patterns(self, line: str):
        """Detect special patterns in output"""
        # Detect workflow step beginning: "[tag] Agent tag task beginning."
        begin_match = re.search(
            r'\[([^\]]+)\]\s*Agent\s+\S+\s+task\s+beginning', line)
        if begin_match:
            step_name = begin_match.group(1)

            # Skip sub-steps (contain -r0-, -diversity-, etc.)
            if '-r' in step_name and '-' in step_name.split('-r')[-1]:
                print(f'[Runner] Skipping sub-step: {step_name}')
                return

            print(f'[Runner] Detected step beginning: {step_name}')

            # If there's a previous step running, mark it as completed first
            if self._current_step and self._current_step != step_name:
                prev_step = self._current_step
                print(f'[Runner] Auto-completing previous step: {prev_step}')
                if self.on_output:
                    self.on_output({
                        'type': 'step_complete',
                        'content': prev_step,
                        'role': 'assistant',
                        'metadata': {
                            'step': prev_step,
                            'status': 'completed'
                        }
                    })

            self._current_step = step_name
            if step_name not in self._workflow_steps:
                self._workflow_steps.append(step_name)

            # Build step status - all previous steps completed, current running
            step_status = {}
            for i, s in enumerate(self._workflow_steps):
                if s == step_name:
                    step_status[s] = 'running'
                elif i < self._workflow_steps.index(step_name):
                    step_status[s] = 'completed'
                else:
                    step_status[s] = 'pending'

            if self.on_progress:
                self.on_progress({
                    'type': 'workflow',
                    'current_step': step_name,
                    'steps': self._workflow_steps.copy(),
                    'step_status': step_status
                })

            # Send step start message
            if self.on_output:
                self.on_output({
                    'type': 'step_start',
                    'content': step_name,
                    'role': 'assistant',
                    'metadata': {
                        'step': step_name,
                        'status': 'running'
                    }
                })
            return

        # Detect workflow step finished: "[tag] Agent tag task finished."
        end_match = re.search(r'\[([^\]]+)\]\s*Agent\s+\S+\s+task\s+finished',
                              line)
        if end_match:
            step_name = end_match.group(1)

            # Skip sub-steps
            if '-r' in step_name and '-' in step_name.split('-r')[-1]:
                return

            print(f'[Runner] Detected step finished: {step_name}')

            # Build step status dict - all steps up to current are completed
            step_status = {}
            for s in self._workflow_steps:
                step_status[s] = 'completed' if self._workflow_steps.index(
                    s) <= self._workflow_steps.index(step_name) else 'pending'

            if self.on_progress:
                self.on_progress({
                    'type': 'workflow',
                    'current_step': step_name,
                    'steps': self._workflow_steps.copy(),
                    'step_status': step_status
                })

            # Send step complete message
            if self.on_output:
                self.on_output({
                    'type': 'step_complete',
                    'content': step_name,
                    'role': 'assistant',
                    'metadata': {
                        'step': step_name,
                        'status': 'completed'
                    }
                })
            return

        # Detect assistant output: "[tag] [assistant]:"
        if '[assistant]:' in line:
            self._accumulated_output = ''
            return

        # Detect tool calls: "[tag] [tool_calling]:"
        if '[tool_calling]:' in line:
            if self.on_output:
                self.on_output({
                    'type': 'tool_call',
                    'content': 'Calling tool...',
                    'role': 'assistant'
                })
            return

        # Detect file writing
        file_match = re.search(r'writing file:?\s*["\']?([^\s"\']+)["\']?',
                               line.lower())
        if not file_match:
            file_match = re.search(
                r'creating file:?\s*["\']?([^\s"\']+)["\']?', line.lower())
        if file_match and self.on_progress:
            filename = file_match.group(1)
            self.on_progress({
                'type': 'file',
                'file': filename,
                'status': 'writing'
            })
            return

        # Detect file written/created/saved - multiple patterns
        file_keywords = [
            'file created', 'file written', 'file saved', 'saved to:',
            'wrote to', 'generated:', 'output:'
        ]
        if any(keyword in line.lower() for keyword in file_keywords):
            # Try to extract filename with extension
            file_match = re.search(
                r'["\']?([^\s"\'\[\]]+\.[a-zA-Z0-9]+)["\']?', line)
            if file_match and self.on_progress:
                filename = file_match.group(1)
                print(f'[Runner] Detected file output: {filename}')
                # Send as output file
                if self.on_output:
                    self.on_output({
                        'type': 'file_output',
                        'content': filename,
                        'role': 'assistant',
                        'metadata': {
                            'filename': filename
                        }
                    })
                self.on_progress({
                    'type': 'file',
                    'file': filename,
                    'status': 'completed'
                })
            return

        # Detect output file paths (e.g., "output/user_story.txt" standalone)
        output_path_match = re.search(
            r'(?:^|\s)((?:output|projects)/[^\s]+\.[a-zA-Z0-9]+)(?:\s|$)',
            line)
        if output_path_match and self.on_progress:
            filename = output_path_match.group(1)
            print(f'[Runner] Detected output path: {filename}')
            if self.on_output:
                self.on_output({
                    'type': 'file_output',
                    'content': filename,
                    'role': 'assistant',
                    'metadata': {
                        'filename': filename
                    }
                })
            self.on_progress({
                'type': 'file',
                'file': filename,
                'status': 'completed'
            })
            return
