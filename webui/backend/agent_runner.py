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

    async def start(self, query: str):
        """Start the agent"""
        try:
            self._stop_requested = False
            self.is_running = True

            # Build command based on project type
            cmd = self._build_command(query)
            env = self._build_env()

            print('[Runner] Starting agent with command:')
            print(f"[Runner] {' '.join(cmd)}")
            print(f"[Runner] Working directory: {self.project['path']}")

            # Log the command
            if self.on_log:
                self.on_log({
                    'level': 'info',
                    'message': f'Starting agent: {" ".join(cmd[:5])}...',
                    'timestamp': datetime.now().isoformat()
                })

            # Start subprocess
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE,
                env=env,
                cwd=self.project['path'],
                start_new_session=True)

            print(f'[Runner] Process started with PID: {self.process.pid}')

            # Start output reader
            await self._read_output()

        except Exception as e:
            print(f'[Runner] ERROR: {e}')
            import traceback
            traceback.print_exc()
            if self.on_error:
                self.on_error({'message': str(e), 'type': 'startup_error'})

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
                '--trust_remote_code', 'true'
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
        """Read and process output from the subprocess"""
        print('[Runner] Starting to read output...')
        try:
            while self.is_running and self.process and self.process.stdout:
                line = await self.process.stdout.readline()
                if not line:
                    print('[Runner] No more output, breaking...')
                    break

                text = line.decode('utf-8', errors='replace').rstrip()
                print(f'[Runner] Output: {text[:200]}'
                      if len(text) > 200 else f'[Runner] Output: {text}')
                await self._process_line(text)

            # Wait for process to complete
            if self.process:
                return_code = await self.process.wait()
                print(f'[Runner] Process exited with code: {return_code}')

                # If stop was requested, do not report as completion/error
                if self._stop_requested:
                    if self.on_log:
                        self.on_log({
                            'level': 'info',
                            'message': 'Agent stopped by user',
                            'timestamp': datetime.now().isoformat()
                        })
                    return

                if return_code == 0:
                    if self.on_complete:
                        self.on_complete({
                            'status':
                            'success',
                            'message':
                            'Agent completed successfully'
                        })
                else:
                    if self.on_error:
                        self.on_error({
                            'message': f'Agent exited with code {return_code}',
                            'type': 'exit_error',
                            'code': return_code
                        })

        except Exception as e:
            print(f'[Runner] Read error: {e}')
            import traceback
            traceback.print_exc()
            if not self._stop_requested and self.on_error:
                self.on_error({'message': str(e), 'type': 'read_error'})
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
