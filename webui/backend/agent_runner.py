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
        self._waiting_for_input = False  # Track if agent is waiting for user input
        self._waiting_input_sent = False  # Track if waiting_input message was already sent
        self._collecting_assistant_output = False  # Track if we're collecting assistant output
        self._collecting_tool_call = False  # Track if we're collecting tool call info
        self._collecting_tool_result = False  # Track if we're collecting tool result
        self._current_tool_name = None  # Current tool being called
        self._current_tool_args = None  # Current tool arguments
        self._current_tool_result = None  # Current tool result
        self._tool_call_json_buffer = ''  # Buffer for collecting multi-line JSON tool call info
        self._is_chat_mode = project.get(
            'id') == '__chat__'  # Simple chat mode flag
        self._chat_response_buffer = ''  # Buffer for chat mode responses

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
        self._waiting_input_sent = False  # Reset so it can be sent again after next completion
        self.is_running = True  # Ensure process is marked as running
        # Reset chat mode collection state for next response
        self._collecting_assistant_output = False
        self._chat_response_buffer = ''

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
                    cmd.extend(['--llm.openai_api_key', llm_config['api_key']])
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

            # Add edit_file_config from user settings (skip for chat mode)
            if self.project.get('id') != '__chat__':
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
                            include_list = config_data['tools'][
                                'file_system'].get('include', [])
                            if isinstance(
                                    include_list,
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
                        cmd.extend(
                            ['--tools.file_system.exclude', 'edit_file'])

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
        """Read and process output from the subprocess"""
        print('[Runner] Starting to read output...')
        process_exited = False
        empty_line_count = 0  # Track consecutive empty lines after process exit
        try:
            # Continue reading even after process exits to catch all remaining output
            while (self.is_running or process_exited) and self.process:
                # Check if process has exited
                if self.process.returncode is not None and not process_exited:
                    process_exited = True
                    print(
                        f'[Runner] Process exited with code: {self.process.returncode}'
                    )
                    # Continue reading remaining output even after process exits
                    # This ensures we don't miss any URLs or important messages
                    if not self.process.stdout:
                        # If stdout is closed, we can't read more
                        if self._waiting_for_input:
                            self._waiting_for_input = False
                        break

                # Check if stdout is still available
                if not self.process.stdout:
                    print('[Runner] Process stdout is closed')
                    break

                try:
                    # Use shorter timeout after process exits to read remaining data faster
                    timeout = 0.1 if process_exited else 1.0
                    line = await asyncio.wait_for(
                        self.process.stdout.readline(), timeout=timeout)
                except asyncio.TimeoutError:
                    # Timeout - check if we're waiting for input
                    if self._waiting_for_input:
                        # Check if process is still alive
                        if self.process.returncode is None:
                            # Process is still alive, continue waiting
                            continue
                        else:
                            # Process exited, but continue reading remaining output
                            # Try a few more times before giving up
                            if empty_line_count < 3:
                                continue
                            break
                    # Not waiting for input, check if process is still alive
                    if self.process.returncode is not None:
                        # Process exited, try a few more times before giving up
                        if empty_line_count < 3:
                            continue
                        break
                    continue

                if not line:
                    # Empty line - check context
                    if process_exited:
                        # After process exit, count consecutive empty lines
                        empty_line_count += 1
                        # If we get 3 consecutive empty lines/timeouts, assume no more data
                        if empty_line_count >= 3:
                            print('[Runner] No more output after process exit')
                            break
                        # Continue trying to read more
                        continue

                    # Check if agent is waiting for input before breaking
                    if self._waiting_for_input:
                        # Check if process is still alive
                        if self.process.returncode is None:
                            print(
                                '[Runner] Agent is waiting for user input, keeping process alive...'
                            )
                            # Keep process alive and wait for input
                            await asyncio.sleep(
                                0.5)  # Small delay to avoid busy waiting
                            continue
                        else:
                            print(
                                '[Runner] Process exited while waiting for input'
                            )
                            # Process exited, but continue reading any remaining output
                            # Don't break yet - there might be more data in stdout buffer
                            process_exited = True
                            continue
                    print('[Runner] No more output, breaking...')
                    break

                # Reset empty line count when we get actual data
                empty_line_count = 0
                text = line.decode('utf-8', errors='replace').rstrip()
                print(f'[Runner] Output: {text[:200]}'
                      if len(text) > 200 else f'[Runner] Output: {text}')
                try:
                    await self._process_line(text)
                except Exception as e:
                    print(f'[Runner] ERROR processing line: {e}')
                    import traceback
                    traceback.print_exc()

            # Wait for process to complete and handle completion
            if self.process:
                # Get return code if not already available
                if self.process.returncode is None:
                    return_code = await self.process.wait()
                else:
                    return_code = self.process.returncode

                print(f'[Runner] Process exited with code: {return_code}')

                # Flush chat response for chat mode
                self._flush_chat_response()

                # Flush any accumulated assistant output before handling completion
                if self._collecting_assistant_output and self._accumulated_output.strip(
                ):
                    cleaned = re.sub(r'\[INFO:ms_agent\]\s*', '',
                                     self._accumulated_output.strip())
                    cleaned = re.sub(r'\[([^\]]+)\]\s*', '', cleaned, count=1)
                    print(
                        f'[Runner] Flushing accumulated output on process exit: {cleaned[:200]}...'
                    )
                    if cleaned and self.on_output:
                        self.on_output({
                            'type': 'agent_output',
                            'content': cleaned,
                            'role': 'assistant',
                            'metadata': {
                                'agent': self._current_step or 'agent'
                            }
                        })
                    self._accumulated_output = ''
                    self._collecting_assistant_output = False

                # If stop was requested, do not report as completion/error
                if self._stop_requested:
                    if self.on_log:
                        self.on_log({
                            'level': 'info',
                            'message': 'Agent stopped by user',
                            'timestamp': datetime.now().isoformat()
                        })
                    return

                # Complete current step if any before handling exit
                if self._current_step and self.on_output:
                    self.on_output({
                        'type': 'step_complete',
                        'content': self._current_step,
                        'role': 'assistant',
                        'metadata': {
                            'step': self._current_step,
                            'status': 'completed'
                        }
                    })
                    # If Refine step completes successfully, it should be waiting for input
                    if return_code == 0 and self._current_step.lower(
                    ) == 'refine':
                        self._waiting_for_input = True
                    self._current_step = None

                # If was waiting for input but process exited, clear waiting state
                if self._waiting_for_input:
                    self._waiting_for_input = False
                    # If process completed successfully, send completion message
                    if return_code == 0:
                        # Send waiting_input message if not already sent
                        if self.on_output and not self._waiting_input_sent:
                            self.on_output({
                                'type':
                                'waiting_input',
                                'content':
                                ('✅ Initial refinement completed. '
                                 'You can now provide additional feedback or modifications.'
                                 ),
                                'role':
                                'system',
                                'metadata': {
                                    'waiting': True
                                }
                            })
                            self._waiting_input_sent = True
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
                                'message':
                                ('Agent process terminated while waiting for input. '
                                 f'Exit code: {return_code}'),
                                'type':
                                'process_exit_error',
                                'code':
                                return_code
                            })
                elif return_code == 0:
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
            if not self._waiting_for_input:
                self.is_running = False
                print('[Runner] Finished reading output')
            else:
                print('[Runner] Process waiting for input, keeping alive...')

    @staticmethod
    def _clean_log_prefix(text: str) -> str:
        """Remove log prefixes like [INFO:ms_agent] [agent_name]"""
        # Remove [INFO:ms_agent] prefix
        text = re.sub(r'\[INFO:ms_agent\]\s*', '', text)
        # Remove [agent_name] prefix (e.g., [orchestrator])
        text = re.sub(r'^\[([^\]]+)\]\s*', '', text)
        return text.strip()

    async def _process_chat_line(self, line: str):
        """Simple chat mode - send response and wait for next input"""
        # Detect [assistant]: marker - next lines will be the response
        if '[assistant]:' in line:
            self._collecting_assistant_output = True
            self._chat_response_buffer = ''
            return

        # If collecting, send content immediately as complete
        if self._collecting_assistant_output:
            cleaned = self._clean_log_prefix(line)
            if cleaned:
                if self._chat_response_buffer:
                    self._chat_response_buffer += '\n' + cleaned
                else:
                    self._chat_response_buffer = cleaned
                # Send immediately with done=true (non-streaming mode)
                print(
                    f'[Runner] Chat response: {len(self._chat_response_buffer)} chars'
                )
                if self.on_output:
                    self.on_output({
                        'type': 'stream',
                        'content': self._chat_response_buffer,
                        'role': 'assistant',
                        'done': True
                    })
                # Mark as waiting for input - process is still running
                self._waiting_for_input = True

    def _flush_chat_response(self):
        """Send final chat response with done=True"""
        if self._is_chat_mode and self._chat_response_buffer.strip(
        ) and self.on_output:
            print(
                f'[Runner] Chat complete: {len(self._chat_response_buffer)} chars'
            )
            self.on_output({
                'type': 'stream',
                'content': self._chat_response_buffer.strip(),
                'role': 'assistant',
                'done': True
            })
            self._chat_response_buffer = ''
            self._collecting_assistant_output = False

    async def _process_line(self, line: str):
        """Process a line of output"""
        # Skip usage statistics lines
        if '[usage]' in line or '[usage_total]' in line:
            return

        # Simple chat mode: just capture assistant output
        if self._is_chat_mode:
            await self._process_chat_line(line)
            return

        # Skip lines without agent name (generic system messages)
        # Pattern: [INFO:ms_agent] without [agent_name] afterwards
        if '[INFO:ms_agent]' in line:
            # Check if there's an agent name tag [xxx] after [INFO:ms_agent]
            import re
            if not re.search(r'\[INFO:ms_agent\]\s*\[([^\]]+)\]', line):
                return

        # Log the cleaned line
        if self.on_log:
            log_level = self._detect_log_level(line)
            cleaned_message = self._clean_log_prefix(line)
            await self.on_log({
                'level':
                log_level,
                'message':
                cleaned_message if cleaned_message else line,
                'timestamp':
                datetime.now().isoformat()
            })

        # Parse for special patterns (use original line for pattern matching)
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

    def _scan_and_send_output_files(self, programmer_step=None):
        """Read tasks.txt to get all generated files with their completion status"""
        try:
            project_path = self.project.get('path')
            if not project_path:
                return

            # tasks.txt path: projects/code_genesis/output/tasks.txt
            tasks_file = os.path.join(project_path, 'output', 'tasks.txt')

            if not os.path.exists(tasks_file):
                print(f'[Runner] tasks.txt not found: {tasks_file}')
                return

            print(f'[Runner] Reading tasks.txt: {tasks_file}')

            # Read and parse tasks.txt
            with open(tasks_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            generated_files = []

            for line in lines:
                line = line.strip()
                # Skip header line and empty lines
                if not line or line.startswith('Files in'):
                    continue

                # Parse format: "css/styles.css: ✅Built"
                if ':' in line and '✅' in line:
                    file_path = line.split(':')[0].strip()
                    generated_files.append(file_path)

            print(
                f'[Runner] Found {len(generated_files)} files in tasks.txt: {generated_files}'
            )

            # Send all files in one batch
            if generated_files and self.on_output:
                self.on_output({
                    'type': 'file_output',
                    'content': generated_files,  # Send as array
                    'role': 'assistant',
                    'metadata': {
                        'files': generated_files,
                        'source': 'tasks.txt'
                    }
                })

        except Exception as e:
            print(f'[Runner] Error reading tasks.txt: {e}')
            import traceback
            traceback.print_exc()

    async def _detect_patterns(self, line: str):
        """Detect special patterns in output"""
        # IMPORTANT: Check for deployment URL FIRST, before any other patterns that might return early
        # This ensures URLs are always detected even if other patterns match
        url_match = None
        # Pattern 1: "url": "https://..."
        url_match = re.search(r'"url":\s*"(https?://[^"]+)"', line)
        # Pattern 2: Direct URL like "https://mcp.edgeone.site/share/..."
        if not url_match:
            url_match = re.search(r'(https?://mcp\.edgeone\.site/[^\s]+)',
                                  line)
        # Pattern 3: EdgeOne Pages URL like "https://...edgeone.cool?..."
        # BUT skip if this is a curl command line (testing command, not actual deployment URL)
        if not url_match and 'curl -s' not in line and 'curl ' not in line:
            url_match = re.search(r'(https?://[^\s]*edgeone\.cool[^\s]*)',
                                  line)
        # Pattern 4: Also check for edgeone.site URLs in any format (fallback)
        # BUT skip if this is a curl command line
        if not url_match and 'curl -s' not in line and 'curl ' not in line:
            url_match = re.search(r'(https?://[^\s]*edgeone\.site[^\s]*)',
                                  line)
        if url_match:
            deployment_url = url_match.group(1)
            # Clean up escaped characters in URL (e.g., \& -> &)
            deployment_url = deployment_url.replace('\\&', '&')
            print(
                f'[Runner] Detected deployment URL (early): {deployment_url} from line: {line[:100]}'
            )
            if self.on_output:
                self.on_output({
                    'type': 'deployment_url',
                    'content': deployment_url,
                    'role': 'assistant',
                    'metadata': {
                        'url': deployment_url
                    }
                })
            # Continue processing - don't return yet, other patterns might also match

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

            # Skip sub-steps and programmer agents (handled separately)
            if (('-r' in step_name and '-' in step_name.split('-r')[-1])
                    or step_name.startswith('programmer-')):
                return

            print(f'[Runner] Step beginning: {step_name}')

            # Flush previous step if exists
            if self._current_step and self._accumulated_output.strip():
                cleaned = re.sub(r'\[INFO:ms_agent\]\s*', '',
                                 self._accumulated_output.strip())
                cleaned = re.sub(r'\[([^\]]+)\]\s*', '', cleaned, count=1)
                if cleaned and self.on_output:
                    self.on_output({
                        'type': 'agent_output',
                        'content': cleaned,
                        'role': 'assistant',
                        'metadata': {
                            'agent': self._current_step
                        }
                    })
                self._accumulated_output = ''
                self._collecting_assistant_output = False

            if self._current_step and self.on_output:
                self.on_output({
                    'type': 'step_complete',
                    'content': self._current_step,
                    'role': 'assistant',
                    'metadata': {
                        'step': self._current_step,
                        'status': 'completed'
                    }
                })

            # Start new step
            self._current_step = step_name
            if step_name not in self._workflow_steps:
                self._workflow_steps.append(step_name)

            step_status = {
                s: ('completed' if i < self._workflow_steps.index(step_name)
                    else 'running' if s == step_name else 'pending')
                for i, s in enumerate(self._workflow_steps)
            }

            if self.on_progress:
                self.on_progress({
                    'type': 'workflow',
                    'current_step': step_name,
                    'steps': self._workflow_steps.copy(),
                    'step_status': step_status
                })

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

            # If Refine step is starting, scan tasks.txt for all generated files
            # This ensures files are detected after Coding phase completes
            if step_name.lower() == 'refine':
                self._scan_and_send_output_files()

            return

        # Detect programmer-xxx pattern (first occurrence signals coding start)
        programmer_match = re.search(r'\[programmer-([^\]]+)\]', line)
        if programmer_match:
            programmer_agent = f'programmer-{programmer_match.group(1)}'

            # If this is FIRST programmer agent, trigger coding step start
            if not self._current_step or not self._current_step.startswith(
                    'programmer-'):
                print(
                    f'[Runner] First programmer agent detected: {programmer_agent} - starting coding step'
                )

                # Flush previous step's output
                if self._current_step and self._accumulated_output.strip():
                    cleaned = re.sub(r'\[INFO:ms_agent\]\s*', '',
                                     self._accumulated_output.strip())
                    cleaned = re.sub(r'\[([^\]]+)\]\s*', '', cleaned, count=1)
                    if cleaned and self.on_output:
                        self.on_output({
                            'type': 'agent_output',
                            'content': cleaned,
                            'role': 'assistant',
                            'metadata': {
                                'agent': self._current_step
                            }
                        })
                    self._accumulated_output = ''
                    self._collecting_assistant_output = False

                # Mark previous step complete
                if self._current_step and self.on_output:
                    self.on_output({
                        'type': 'step_complete',
                        'content': self._current_step,
                        'role': 'assistant',
                        'metadata': {
                            'step': self._current_step,
                            'status': 'completed'
                        }
                    })

                # Start coding step
                self._current_step = programmer_agent
                if 'coding' not in self._workflow_steps:
                    self._workflow_steps.append('coding')

                step_status = {
                    s: ('completed' if i < self._workflow_steps.index('coding')
                        else 'running' if s == 'coding' else 'pending')
                    for i, s in enumerate(self._workflow_steps)
                }

                if self.on_progress:
                    self.on_progress({
                        'type': 'workflow',
                        'current_step': 'coding',
                        'steps': self._workflow_steps.copy(),
                        'step_status': step_status
                    })

                if self.on_output:
                    self.on_output({
                        'type': 'step_start',
                        'content': 'coding',
                        'role': 'assistant',
                        'metadata': {
                            'step': 'coding',
                            'status': 'running'
                        }
                    })

            # Update current programmer agent
            elif programmer_agent != self._current_step:
                self._current_step = programmer_agent

        # Helper to flush accumulated assistant output
        def flush_accumulated_output():
            print(f'[Runner] flush_accumulated_output called: '
                  f'collecting={self._collecting_assistant_output}, '
                  f'buffer_len={len(self._accumulated_output)}')
            print(
                f'[Runner] Buffer content: {self._accumulated_output[:200]}...'
                if len(self._accumulated_output) > 200 else
                f'[Runner] Buffer content: {self._accumulated_output}')
            if self._collecting_assistant_output and self._accumulated_output.strip(
            ):
                # Clean log prefixes
                cleaned_content = re.sub(r'\[INFO:ms_agent\]\s*', '',
                                         self._accumulated_output.strip())
                cleaned_content = re.sub(
                    r'\[([^\]]+)\]\s*', '', cleaned_content, count=1)
                print(
                    f'[Runner] Flushing assistant output: {cleaned_content[:100]}...'
                )

                # Map agent name for display
                agent_name = self._current_step or 'agent'
                display_agent = agent_name
                if agent_name.startswith('programmer-'):
                    display_agent = 'coding'

                if cleaned_content and self.on_output:
                    self.on_output({
                        'type': 'agent_output',
                        'content': cleaned_content,
                        'role': 'assistant',
                        'metadata': {
                            'agent': display_agent
                        }
                    })
                self._accumulated_output = ''
                self._collecting_assistant_output = False
            else:
                print(f'[Runner] flush_accumulated_output skipped: '
                      f'collecting={self._collecting_assistant_output}, '
                      f'has_content={bool(self._accumulated_output.strip())}')

        # Detect workflow step finished: "[tag] Agent tag task finished."
        end_match = re.search(r'\[([^\]]+)\]\s*Agent\s+\S+\s+task\s+finished',
                              line)
        if end_match:
            step_name = end_match.group(1)

            # Skip install (handled by programmer detection) and sub-steps
            if step_name == 'install' or ('-r' in step_name and '-'
                                          in step_name.split('-r')[-1]):
                return

            # Skip flush for refine (already flushed during collection)
            if step_name.lower() != 'refine':
                flush_accumulated_output()
            print(f'[Runner] Step finished: {step_name}')

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

            # Clear current step since it's completed
            self._current_step = None
            return

        # Clean log prefixes from line
        # Detect assistant output: "[tag] [assistant]:"
        if '[assistant]:' in line:
            in_coding = self._current_step and self._current_step.startswith(
                'programmer-')

            if not in_coding:
                # Start collecting (don't send first line immediately)
                self._accumulated_output = ''
                self._collecting_assistant_output = True
                # Extract content after [assistant]: if any on same line
                parts = line.split('[assistant]:', 1)
                if len(parts) > 1 and parts[1].strip():
                    content = self._clean_log_prefix(parts[1].strip())
                    if content:
                        self._accumulated_output = content + '\n'
            else:
                # In coding phase: don't collect
                self._collecting_assistant_output = False
                self._accumulated_output = ''
            # Don't return - continue to process line for file_output detection

        # Continue collecting assistant output
        elif self._collecting_assistant_output:
            # Skip if in coding phase
            if self._current_step and self._current_step.startswith(
                    'programmer-'):
                self._collecting_assistant_output = False
                self._accumulated_output = ''
                # Don't return - continue processing
            else:
                # Check if new pattern starts
                if '[tool_calling]:' in line or ('[assistant]:' in line
                                                 and 'Agent' not in line):
                    if self._accumulated_output.strip():
                        cleaned = self._clean_log_prefix(
                            self._accumulated_output.strip())
                        if cleaned and self.on_output:
                            self.on_output({
                                'type': 'agent_output',
                                'content': cleaned,
                                'role': 'assistant',
                                'metadata': {
                                    'agent': self._current_step or 'agent'
                                }
                            })
                    self._accumulated_output = ''
                    self._collecting_assistant_output = False
                else:
                    # Accumulate line but also check for deployment URL and waiting_input
                    if line.strip():
                        cleaned_line = self._clean_log_prefix(line)
                        if cleaned_line:
                            self._accumulated_output += cleaned_line + '\n'
                            # Check for EdgeOne deployment URL in this line
                            url_match = re.search(
                                r'(https?://[^\s]*edgeone\.cool[^\s]*)',
                                cleaned_line)
                            if url_match:
                                deployment_url = url_match.group(1)
                                # Clean up escaped characters in URL (e.g., \& -> &)
                                deployment_url = deployment_url.replace(
                                    '\\&', '&')
                                print(
                                    f'[Runner] Detected deployment URL in assistant: {deployment_url}'
                                )
                                if self.on_output:
                                    self.on_output({
                                        'type': 'deployment_url',
                                        'content': deployment_url,
                                        'role': 'assistant',
                                        'metadata': {
                                            'url': deployment_url
                                        }
                                    })
                            # Check for waiting for input pattern
                            if ('Waiting for user feedback' in line
                                    or 'Waiting for user input from stdin'
                                    in line):
                                print('[Runner] Agent waiting for user input')
                                self._waiting_for_input = True
                                if self.on_output and not self._waiting_input_sent:
                                    self.on_output({
                                        'type':
                                        'waiting_input',
                                        'content':
                                        ('✅ Initial refinement completed. '
                                         'You can now provide additional feedback or modifications.'
                                         ),
                                        'role':
                                        'system',
                                        'metadata': {
                                            'waiting': True
                                        }
                                    })
                                    self._waiting_input_sent = True
                    return

        # Detect tool calls: "[tag] [tool_calling]:"
        if '[tool_calling]:' in line:
            self._collecting_tool_call = True
            self._current_tool_name = None
            self._current_tool_args = None
            self._tool_call_json_buffer = ''

            # Check if JSON starts on the same line after [tool_calling]:
            parts = line.split('[tool_calling]:', 1)
            if len(parts) > 1:
                json_part = parts[1].strip()
                if json_part.startswith('{'):
                    self._tool_call_json_buffer = json_part
                elif json_part:
                    # Try to extract tool name directly if it's not JSON format
                    tool_match = re.search(r'([\w\-]+(?:---[\w\-]+)?)',
                                           json_part)
                    if tool_match:
                        self._current_tool_name = tool_match.group(1)
            return

        # Continue collecting tool call info
        if self._collecting_tool_call:
            # Extract agent name from line if available (for better matching)
            agent_name_from_line = None
            if '[INFO:ms_agent]' in line:
                agent_match = re.search(r'\[INFO:ms_agent\]\s*\[([^\]]+)\]',
                                        line)
                if agent_match:
                    agent_name_from_line = agent_match.group(1)

            # Clean log prefixes from line before processing
            cleaned_line = self._clean_log_prefix(line)

            # Accumulate JSON lines
            if cleaned_line.strip():
                # Remove agent tag prefix if present (e.g., [programmer-config.json])
                cleaned_line = re.sub(r'^\[[^\]]+\]\s*', '', cleaned_line)

                # Skip truncation marker lines (just "...")
                if cleaned_line.strip() == '...':
                    return

                # Skip lines that are just a trailing backslash (truncated escape sequence)
                if cleaned_line.strip() == '\\':
                    return

                if self._tool_call_json_buffer:
                    self._tool_call_json_buffer += cleaned_line  # Don't add newline, keep JSON compact
                elif cleaned_line.strip().startswith('{'):
                    self._tool_call_json_buffer = cleaned_line.strip()
                else:
                    self._tool_call_json_buffer += cleaned_line

            # Only try to parse when buffer contains tool_name and ends with }
            if (self._tool_call_json_buffer
                    and '"tool_name"' in self._tool_call_json_buffer
                    and self._tool_call_json_buffer.strip().endswith('}')):
                try:
                    import json
                    tool_info = json.loads(self._tool_call_json_buffer)
                    print('[Runner] Parsed tool JSON successfully')
                    tool_name = tool_info.get('tool_name') or tool_info.get(
                        'name', 'unknown')
                    tool_args = tool_info.get('arguments', {})
                    print(f'[Runner] Extracted tool_name: {tool_name}')
                    if tool_name and tool_name != 'unknown':
                        self._current_tool_name = tool_name
                        self._current_tool_args = tool_args
                        agent_name = agent_name_from_line or self._current_step or 'agent'
                        print(
                            f'[Runner] Sending tool call: {tool_name}, agent: {agent_name}'
                        )
                        if self.on_output:
                            self.on_output({
                                'type': 'tool_call',
                                'content': f'调用工具: {tool_name}',
                                'role': 'assistant',
                                'metadata': {
                                    'tool_name': tool_name,
                                    'tool_args': tool_args,
                                    'agent': agent_name
                                }
                            })
                        # Clear buffer but KEEP collecting - there may be more tool calls
                        self._tool_call_json_buffer = ''
                        # Don't return or stop collecting - next line might be another tool call JSON
                    else:
                        print(
                            f'[Runner] WARNING: Invalid tool_name: {tool_name}'
                        )
                except json.JSONDecodeError as e:
                    # JSON not complete yet, keep collecting
                    # Only log if we have tool_name - helps debug parsing issues
                    if '"tool_name"' in self._tool_call_json_buffer:
                        print(
                            f'[Runner] JSON incomplete, continuing... (error: {str(e)[:50]})'
                        )
                except Exception as e:
                    print(f'[Runner] Error parsing tool JSON: {e}')

            # Check if we hit a new pattern, stop collecting
            if '[assistant]:' in line or 'Agent' in line and 'task' in line or '[tool_result]:' in line:
                # If we have partial data, try to send it
                if self._tool_call_json_buffer:
                    tool_name_match = re.search(r'"tool_name"\s*:\s*"([^"]+)"',
                                                self._tool_call_json_buffer)
                    if tool_name_match:
                        tool_name = tool_name_match.group(1)
                        # Try to extract arguments - handle nested JSON objects
                        args_start = self._tool_call_json_buffer.find(
                            '"arguments"')
                        tool_args = {}
                        if args_start != -1:
                            brace_start = self._tool_call_json_buffer.find(
                                '{', args_start)
                            if brace_start != -1:
                                brace_count = 0
                                brace_end = brace_start
                                for i in range(
                                        brace_start,
                                        len(self._tool_call_json_buffer)):
                                    if self._tool_call_json_buffer[i] == '{':
                                        brace_count += 1
                                    elif self._tool_call_json_buffer[i] == '}':
                                        brace_count -= 1
                                        if brace_count == 0:
                                            brace_end = i + 1
                                            break

                                if brace_end > brace_start:
                                    args_str = self._tool_call_json_buffer[
                                        brace_start:brace_end]
                                    try:
                                        tool_args = json.loads(args_str)
                                    except Exception:
                                        pass

                        # Determine agent name - prefer extracted from line, then current step
                        agent_name = agent_name_from_line or self._current_step or 'agent'
                        print(
                            f'[Runner] Sending tool call (pattern end): '
                            f'{tool_name}, agent: {agent_name}, args: {tool_args}'
                        )
                        if self.on_output:
                            self.on_output({
                                'type': 'tool_call',
                                'content': f'调用工具: {tool_name}',
                                'role': 'assistant',
                                'metadata': {
                                    'tool_name': tool_name,
                                    'tool_args': tool_args,
                                    'agent': agent_name
                                }
                            })
                self._collecting_tool_call = False
                self._tool_call_json_buffer = ''
            return

        # Detect tool results: "[tag] [tool_result]:"
        if '[tool_result]:' in line:
            self._collecting_tool_result = True
            # Extract result content
            parts = line.split('[tool_result]:', 1)
            if len(parts) > 1:
                result_content = parts[1].strip()
                if result_content:
                    self._current_tool_result = result_content
                    # Send tool result immediately if we have tool name
                    if self._current_tool_name and self.on_output:
                        self.on_output({
                            'type': 'tool_result',
                            'content': f'工具 {self._current_tool_name} 执行完成',
                            'role': 'assistant',
                            'metadata': {
                                'tool_name': self._current_tool_name,
                                'tool_result': result_content,
                                'agent': self._current_step or 'agent'
                            }
                        })
                        # Reset tool info
                        self._current_tool_name = None
                        self._current_tool_result = None
                        self._collecting_tool_result = False
            return

        # Continue collecting tool result
        if self._collecting_tool_result:
            # Accumulate result content
            if line.strip() and not line.strip().startswith('['):
                if self._current_tool_result:
                    self._current_tool_result += '\n' + line
                else:
                    self._current_tool_result = line

                # Check for EdgeOne deployment URL in tool result
                # Pattern 1: JSON format with edgeone.cool or edgeone.site
                url_match = re.search(
                    r'"url":\s*"(https?://[^"]+edgeone\.(cool|site)[^"]+)"',
                    line)
                # Pattern 2: Direct URL with edgeone.cool or edgeone.site
                if not url_match:
                    url_match = re.search(
                        r'(https?://[^\s]*edgeone\.(cool|site)[^\s]*)', line)
                if url_match:
                    deployment_url = url_match.group(1)
                    # Clean up escaped characters in URL (e.g., \& -> &)
                    deployment_url = deployment_url.replace('\\&', '&')
                    print(
                        f'[Runner] Detected deployment URL in tool result: {deployment_url}'
                    )
                    if self.on_output:
                        self.on_output({
                            'type': 'deployment_url',
                            'content': deployment_url,
                            'role': 'assistant',
                            'metadata': {
                                'url': deployment_url
                            }
                        })
                        # After deployment success, prompt user for further input
                        self._waiting_for_input = True
                        if not self._waiting_input_sent:
                            self.on_output({
                                'type': 'waiting_input',
                                'content':
                                'You can now provide additional feedback or visit the deployed site.',
                                'role': 'system',
                                'metadata': {
                                    'waiting': True,
                                    'deployment_complete': True
                                }
                            })
                            self._waiting_input_sent = True

                # Send result if we have tool name and accumulated enough content
                if self._current_tool_name and len(
                        self._current_tool_result) > 100 and self.on_output:
                    self.on_output({
                        'type': 'tool_result',
                        'content': f'工具 {self._current_tool_name} 执行完成',
                        'role': 'assistant',
                        'metadata': {
                            'tool_name': self._current_tool_name,
                            'tool_result': self._current_tool_result,
                            'agent': self._current_step or 'agent'
                        }
                    })
                    # Reset
                    self._current_tool_name = None
                    self._current_tool_result = None
                    self._collecting_tool_result = False
            elif '[assistant]:' in line or '[tool_calling]:' in line or 'Agent' in line and 'task' in line:
                # Hit a new pattern, send accumulated result
                if self._current_tool_name and self._current_tool_result and self.on_output:
                    self.on_output({
                        'type': 'tool_result',
                        'content': f'工具 {self._current_tool_name} 执行完成',
                        'role': 'assistant',
                        'metadata': {
                            'tool_name': self._current_tool_name,
                            'tool_result': self._current_tool_result,
                            'agent': self._current_step or 'agent'
                        }
                    })
                self._current_tool_name = None
                self._current_tool_result = None
                self._collecting_tool_result = False
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
                    # Only send progress update (file_output will be sent from tasks.txt)
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
            # Only send progress update (file_output will be sent from tasks.txt)
            self.on_progress({
                'type': 'file',
                'file': filename,
                'status': 'completed'
            })
            return

        # Deployment URL detection moved to the beginning of _detect_patterns
        # to ensure it's always checked before any early returns

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
            if self.on_output and not self._waiting_input_sent:
                self.on_output({
                    'type': 'waiting_input',
                    'content':
                    '✅ Initial refinement completed. You can now provide additional feedback or modifications.',
                    'role': 'system',
                    'metadata': {
                        'waiting': True
                    }
                })
                self._waiting_input_sent = True
            return
