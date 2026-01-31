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

import yaml


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
                 on_error: Callable[[Dict[str, Any]], None] = None,
                 workflow_type: str = 'standard'):
        self.session_id = session_id
        self.project = project
        self.config_manager = config_manager
        self.on_output = on_output
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.on_error = on_error
        self._workflow_type = workflow_type

        self.process: Optional[asyncio.subprocess.Process] = None
        self.is_running = False
        self._accumulated_output = ''
        self._current_step = None
        self._workflow_steps = []
        self._stop_requested = False
        self._waiting_for_input = False  # Track if agent is waiting for user input

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
        # Check if process is still alive and stdin is available
        if not self.process:
            print('[Runner] ERROR: Process is None, cannot send input')
            if self.on_error:
                self.on_error({
                    'message':
                    'Agent process is not running. Please start a new conversation.',
                    'type': 'input_error'
                })
            return

        # Check if process has exited
        if self.process.returncode is not None:
            print(
                f'[Runner] ERROR: Process has exited with code {self.process.returncode}, cannot send input'
            )
            if self.on_error:
                self.on_error({
                    'message':
                    'Agent process has terminated. Please start a new conversation.',
                    'type': 'input_error'
                })
            return

        # Check if stdin is available
        if not self.process.stdin:
            print('[Runner] ERROR: Process stdin is None, cannot send input')
            if self.on_error:
                self.on_error({
                    'message':
                    'Cannot send input: process stdin is not available.',
                    'type': 'input_error'
                })
            return

        print(f'[Runner] Sending input to agent: {text[:100]}...')
        self._waiting_for_input = False  # Reset waiting flag when sending input
        self.is_running = True  # Ensure process is marked as running

        try:
            self.process.stdin.write((text + '\n').encode())
            await self.process.stdin.drain()
            print('[Runner] Input sent successfully')
        except (BrokenPipeError, RuntimeError, OSError) as e:
            print(f'[Runner] ERROR: Failed to send input: {e}')
            if self.on_error:
                self.on_error({
                    'message':
                    f'Failed to send input: Process may have terminated. Error: {str(e)}',
                    'type': 'input_error'
                })
            # Mark process as not running
            self.is_running = False
            self._waiting_for_input = False

    def _build_command(self, query: str) -> list:
        """Build the command to run the agent"""
        project_type = self.project.get('type')
        project_path = self.project['path']
        config_file = self.project.get('config_file', '')

        # Get workflow_type from session if available
        # This allows switching between standard and simple workflow for code_genesis
        workflow_type = getattr(self, '_workflow_type', 'standard')
        if workflow_type == 'simple' and project_type == 'workflow':
            # For code_genesis with simple workflow, use simple_workflow.yaml
            simple_config_file = os.path.join(project_path,
                                              'simple_workflow.yaml')
            if os.path.exists(simple_config_file):
                config_file = simple_config_file

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

            # Add LLM config from user settings
            llm_config = self.config_manager.get_llm_config()
            if llm_config.get('api_key'):
                provider = llm_config.get('provider', 'modelscope')
                if provider == 'modelscope':
                    cmd.extend(['--modelscope_api_key', llm_config['api_key']])
                elif provider == 'openai':
                    cmd.extend(['--openai_api_key', llm_config['api_key']])
                    # Set llm.service to openai to ensure the correct service is used
                    cmd.extend(['--llm.service', 'openai'])
                    # Pass base_url if set by user
                    if llm_config.get('base_url'):
                        cmd.extend(
                            ['--llm.openai_base_url', llm_config['base_url']])
                    # Pass model if set by user
                    if llm_config.get('model'):
                        cmd.extend(['--llm.model', llm_config['model']])
                    # Pass temperature if set by user (in generation_config)
                    if llm_config.get('temperature') is not None:
                        cmd.extend([
                            '--generation_config.temperature',
                            str(llm_config['temperature'])
                        ])
                    # Pass max_tokens if set by user (in generation_config)
                    if llm_config.get('max_tokens'):
                        cmd.extend([
                            '--generation_config.max_tokens',
                            str(llm_config['max_tokens'])
                        ])

            # Add edit_file_config from user settings
            edit_file_config = self.config_manager.get_edit_file_config()
            if edit_file_config.get('api_key'):
                # If API key is provided, pass edit_file_config
                cmd.extend([
                    '--tools.file_system.edit_file_config.api_key',
                    edit_file_config['api_key']
                ])
                if edit_file_config.get('base_url'):
                    cmd.extend([
                        '--tools.file_system.edit_file_config.base_url',
                        edit_file_config['base_url']
                    ])
                if edit_file_config.get('diff_model'):
                    cmd.extend([
                        '--tools.file_system.edit_file_config.diff_model',
                        edit_file_config['diff_model']
                    ])
            else:
                # If no API key, exclude edit_file from tools
                # Read the current include list from config file and remove edit_file
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config_data = yaml.safe_load(f)
                    if config_data and 'tools' in config_data and 'file_system' in config_data[
                            'tools']:
                        include_list = config_data['tools']['file_system'].get(
                            'include', [])
                        if isinstance(include_list,
                                      list) and 'edit_file' in include_list:
                            # Remove edit_file from the list
                            filtered_include = [
                                tool for tool in include_list
                                if tool != 'edit_file'
                            ]
                            # Pass the filtered list as comma-separated string
                            cmd.extend([
                                '--tools.file_system.include',
                                ','.join(filtered_include)
                            ])
                except Exception as e:
                    print(
                        f'[Runner] Warning: Could not read config file to exclude edit_file: {e}'
                    )
                    # Fallback: explicitly exclude edit_file
                    cmd.extend(['--tools.file_system.exclude', 'edit_file'])

            # Add EdgeOne Pages API token and project name from user settings
            edgeone_pages_config = self.config_manager.get_edgeone_pages_config(
            )
            if edgeone_pages_config.get('api_token'):
                # If API token is provided, pass it to the MCP server config
                cmd.extend([
                    '--tools.edgeone-pages-mcp.env.EDGEONE_PAGES_API_TOKEN',
                    edgeone_pages_config['api_token']
                ])
            if edgeone_pages_config.get('project_name'):
                # If project name is provided, pass it to the MCP server config
                cmd.extend([
                    '--tools.edgeone-pages-mcp.env.EDGEONE_PAGES_PROJECT_NAME',
                    edgeone_pages_config['project_name']
                ])

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
        # Detect OpenAI API errors and other API errors
        # Check for OpenAI error patterns
        if 'openai.' in line.lower() and ('error' in line.lower()
                                          or 'Error' in line):
            error_message = line.strip()
            # Try to extract error details from the line
            # Pattern: openai.NotFoundError: Error code: 404 - {'error': {'message': '...', ...}}
            json_match = re.search(r'\{.*?\}', error_message, re.DOTALL)
            if json_match:
                try:
                    import json
                    error_data = json.loads(json_match.group(0))
                    if 'error' in error_data and 'message' in error_data[
                            'error']:
                        error_msg = error_data['error']['message']
                        error_type = error_data['error'].get(
                            'type', 'API Error')
                        error_message = f'**{error_type}**: {error_msg}'
                except Exception:
                    pass

            print(f'[Runner] Detected API error: {error_message}')
            if self.on_error:
                self.on_error({'message': error_message, 'type': 'api_error'})
            # Also send as output message so it appears in the conversation
            if self.on_output:
                self.on_output({
                    'type': 'error',
                    'content': error_message,
                    'role': 'system',
                    'metadata': {
                        'error_type': 'api_error'
                    }
                })
            return

        # Detect other error patterns
        error_patterns = [
            r'Error code:\s*(\d+)\s*-\s*({.*?})',
        ]

        for pattern in error_patterns:
            error_match = re.search(pattern, line, re.IGNORECASE | re.DOTALL)
            if error_match:
                error_message = line.strip()
                # Try to extract JSON error details if available
                json_match = re.search(r'\{.*?\}', error_message, re.DOTALL)
                if json_match:
                    try:
                        import json
                        error_data = json.loads(json_match.group(0))
                        if 'error' in error_data and 'message' in error_data[
                                'error']:
                            error_msg = error_data['error']['message']
                            error_type = error_data['error'].get(
                                'type', 'API Error')
                            error_message = f'**{error_type}**: {error_msg}'
                    except Exception:
                        pass

                print(f'[Runner] Detected API error: {error_message}')
                if self.on_error:
                    self.on_error({
                        'message':
                        error_message,
                        'type':
                        'api_error',
                        'code':
                        error_match.group(1) if error_match.groups() else None
                    })
                # Also send as output message so it appears in the conversation
                if self.on_output:
                    self.on_output({
                        'type': 'error',
                        'content': error_message,
                        'role': 'system',
                        'metadata': {
                            'error_type': 'api_error'
                        }
                    })
                return

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

            # If refine step finished, check if it's waiting for input
            if step_name.lower() == 'refine':
                # Check if there's a waiting input message in recent output
                # The refine agent will log "Waiting for user feedback" when should_stop is True
                # We'll detect this pattern and mark as waiting for input
                # This will be detected by the "Initial refinement completed" pattern above
                pass

            # Try to match step name - remove 'programmer-' prefix if needed
            if step_name not in self._workflow_steps:
                # Try removing 'programmer-' prefix to match actual step name
                if step_name.startswith('programmer-'):
                    base_name = step_name.replace('programmer-', '', 1)
                    if base_name in self._workflow_steps:
                        step_name = base_name
                    else:
                        # Add the original step name if base name not found
                        self._workflow_steps.append(step_name)
                else:
                    # Add step if not in list
                    self._workflow_steps.append(step_name)

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
            # More strict pattern: must have a proper filename with extension, not just numbers
            file_match = re.search(
                r'["\']?([a-zA-Z0-9_\-][^\s"\'\/\[\]]*\.[a-zA-Z0-9]+)["\']?',
                line)
            if file_match and self.on_progress:
                filename = file_match.group(1)
                # Validate filename: must not be just numbers or version numbers like "0.0"
                if filename and not re.match(r'^\d+\.\d+$',
                                             filename) and len(filename) > 2:
                    # Strip 'programmer-' prefix from filename
                    if filename.startswith('programmer-'):
                        filename = filename[len('programmer-'):]
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
            # Strip 'programmer-' prefix from basename only (not from path)
            # Split path and filename
            if '/' in filename:
                parts = filename.rsplit('/', 1)
                if len(parts) == 2 and parts[1].startswith('programmer-'):
                    parts[1] = parts[1][len('programmer-'):]
                    filename = '/'.join(parts)
            elif filename.startswith('programmer-'):
                filename = filename[len('programmer-'):]
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

        # Detect EdgeOne deployment URL
        # Pattern 1: "url": "https://..."
        url_match = re.search(r'"url":\s*"(https?://[^"]+)"', line)
        # Pattern 2: Direct URL like "https://mcp.edgeone.site/share/..."
        if not url_match:
            url_match = re.search(r'(https?://mcp\.edgeone\.site/[^\s]+)',
                                  line)
        # Pattern 3: EdgeOne Pages URL like "https://...edgeone.cool?..."
        if not url_match:
            url_match = re.search(r'(https?://[^\s]*edgeone\.cool[^\s]*)',
                                  line)
        if url_match:
            deployment_url = url_match.group(1)
            print(f'[Runner] Detected deployment URL: {deployment_url}')
            if self.on_output:
                self.on_output({
                    'type': 'deployment_url',
                    'content': deployment_url,
                    'role': 'assistant',
                    'metadata': {
                        'url': deployment_url
                    }
                })
            return

        # Detect agent waiting for user input
        # Pattern: "✅ Initial refinement completed. You can now provide..."
        # Also detect: "Agent completed initial refinement. Waiting for user feedback."
        # Also detect: "Waiting for user input from stdin..."
        if ('Initial refinement completed' in line
                or 'provide additional feedback' in line
                or 'Waiting for user feedback' in line
                or 'Agent completed initial refinement' in line
                or 'Waiting for user input from stdin' in line):
            print('[Runner] Agent waiting for user input')
            self._waiting_for_input = True  # Mark that agent is waiting for input
            if self.on_output:
                self.on_output({
                    'type': 'waiting_input',
                    'content':
                    '✅ Initial refinement completed. You can now provide additional feedback or modifications.',
                    'role': 'system',
                    'metadata': {
                        'waiting': True
                    }
                })
            return
