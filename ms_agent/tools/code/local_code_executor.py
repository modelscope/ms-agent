import asyncio
import asyncio.subprocess as ai_subprocess
import inspect
import io
import os
import shutil
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_OUTPUT_DIR
from ms_agent.utils.utils import install_package

logger = get_logger()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _coerce_str(value: Optional[bytes]) -> str:
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


class LocalKernelSession:
    """Manage a local ipykernel instance for stateful notebook execution."""

    def __init__(self,
                 working_dir: Path,
                 env: Optional[Dict[str, str]] = None,
                 kernel_name: str = 'python3',
                 extra_arguments: Optional[List[str]] = None):
        self.working_dir = working_dir
        self.env = env or {}
        self.kernel_name = kernel_name
        self.extra_arguments = extra_arguments or []
        self._km = None
        self._client = None
        self.start_ts: Optional[float] = None
        self.execution_count = 0

    async def start(self) -> None:
        if self._client:
            return

        # Ensure dependencies exist before importing.
        install_package('ipykernel')
        install_package('jupyter-client')

        from jupyter_client import AsyncKernelManager

        logger.info('Starting local ipykernel session...')
        self._km = AsyncKernelManager(
            kernel_name=self.kernel_name,
            env=self.env,
            cwd=str(self.working_dir))

        start_kernel_result = self._km.start_kernel(
            extra_arguments=self.extra_arguments,
            env=self.env,
        )
        if inspect.isawaitable(start_kernel_result):
            await start_kernel_result

        client = self._km.client()
        if inspect.isawaitable(client):
            client = await client
        self._client = client

        start_channels_result = self._client.start_channels()
        if inspect.isawaitable(start_channels_result):
            await start_channels_result

        # Give kernel a moment to fully initialize before accepting code
        await asyncio.sleep(0.5)

        self.start_ts = time.time()
        self.execution_count = 0
        logger.info('Local ipykernel session ready.')

    async def stop(self) -> None:
        if not self._client and not self._km:
            return

        logger.info('Stopping local ipykernel session...')
        if self._client:
            stop_channels_result = self._client.stop_channels()
            if inspect.isawaitable(stop_channels_result):
                await stop_channels_result
        if self._km:
            shutdown_result = self._km.shutdown_kernel(now=True)
            if inspect.isawaitable(shutdown_result):
                await shutdown_result
        self._client = None
        self._km = None
        self.start_ts = None
        self.execution_count = 0

    async def restart(self) -> None:
        if not self._km:
            await self.start()
            return

        logger.info('Restarting local ipykernel session...')
        restart_result = self._km.restart_kernel(now=True)
        if inspect.isawaitable(restart_result):
            await restart_result
        self.execution_count = 0
        self.start_ts = time.time()

    @property
    def client(self):
        return self._client

    @property
    def uptime(self) -> Optional[float]:
        if not self.start_ts:
            return None
        return time.time() - self.start_ts

    async def interrupt(self) -> None:
        if not self._km:
            return

        interrupt_result = self._km.interrupt_kernel()
        if inspect.isawaitable(interrupt_result):
            await interrupt_result

    async def execute(self, code: str, timeout: int) -> Dict[str, Any]:
        if not self._client:
            raise RuntimeError('Kernel client not initialized')

        execute_call = self._client.execute(
            code=code, allow_stdin=False, stop_on_error=False)
        msg_id = await execute_call if inspect.isawaitable(
            execute_call) else execute_call

        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        display_parts: List[str] = []
        error_payload: Optional[Dict[str, Any]] = None

        async def _drain() -> None:
            nonlocal error_payload
            if not self._client:
                raise RuntimeError('Kernel client lost during execution')
            while True:
                try:
                    msg = await self._client.get_iopub_msg(timeout=1)
                except asyncio.TimeoutError:
                    continue

                parent_id = msg['parent_header'].get('msg_id')
                if parent_id != msg_id:
                    continue

                msg_type = msg['msg_type']
                content = msg.get('content', {})

                if msg_type == 'status' and content.get(
                        'execution_state') == 'idle':
                    break
                if msg_type == 'stream':
                    name = content.get('name', 'stdout')
                    text = content.get('text', '')
                    if name == 'stderr':
                        stderr_parts.append(text)
                    else:
                        stdout_parts.append(text)
                elif msg_type in ('execute_result', 'display_data'):
                    data = content.get('data', {}) or {}
                    if 'text/plain' in data:
                        display_parts.append(data['text/plain'])
                    elif 'text/html' in data:
                        display_parts.append(data['text/html'])
                    elif data:
                        display_parts.append(
                            json.dumps(data, ensure_ascii=False))
                elif msg_type == 'error':
                    error_payload = {
                        'ename': content.get('ename'),
                        'evalue': content.get('evalue'),
                        'traceback': content.get('traceback', []),
                    }
                elif msg_type == 'clear_output':
                    stdout_parts.clear()
                    stderr_parts.clear()
                    display_parts.clear()

        try:
            await asyncio.wait_for(_drain(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            logger.warning('Notebook execution timed out, interrupting kernel')
            await self.interrupt()
            raise TimeoutError(
                f'Notebook execution timed out after {timeout} seconds'
            ) from exc

        self.execution_count += 1
        stdout = ''.join(stdout_parts).strip('\n')
        stderr = ''.join(stderr_parts).strip('\n')
        displays = '\n'.join(display_parts).strip('\n')
        output_segments = [
            segment for segment in [stdout, displays] if segment
        ]

        return {
            'output': '\n'.join(output_segments),
            'stderr': stderr,
            'error': error_payload
        }


class LocalCodeExecutionTool(ToolBase):
    """Code execution tool that runs entirely on the local machine."""

    def __init__(self, config):
        super().__init__(config)
        self.output_dir = Path(
            getattr(config, 'output_dir', DEFAULT_OUTPUT_DIR)).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.tool_config = getattr(
            getattr(config, 'tools', None), 'code_executor', None)
        self._notebook_timeout = getattr(self.tool_config, 'notebook_timeout',
                                         60) if self.tool_config else 60
        self._python_timeout = getattr(self.tool_config, 'python_timeout',
                                       30) if self.tool_config else 30
        self._shell_timeout = getattr(self.tool_config, 'shell_timeout',
                                      60) if self.tool_config else 60

        kernel_env = self._build_env('kernel_env', inherit=False)
        shell_env = self._build_env('shell_env', inherit=False)
        self.kernel_session = LocalKernelSession(
            working_dir=self.output_dir, env=kernel_env)
        self.shell_env = shell_env
        self._kernel_lock = asyncio.Lock()
        self._initialized = False

        self.exclude_func(
            getattr(getattr(config, 'tools', None), 'code_executor', None))
        if 'file_operation' not in self.exclude_functions:
            logger.warning(
                'file_operation is not suggested to be included in local code execution tool.'
            )

        results = self._check_dependencies()
        logger.info(f'Dependency check results: {results}\n'
                    f'Make sure to install the missing dependencies.')

        logger.info('LocalCodeExecutionTool initialized (ipykernel based)')

    def _check_dependencies(self) -> None:
        import importlib

        deps = {
            'numpy': 'numpy',
            'pandas': 'pandas',
            'matplotlib': 'matplotlib',
            'seaborn': 'seaborn',
            'scikit-learn': 'sklearn',
            'requests': 'requests',
            'beautifulsoup4': 'bs4',
            'lxml': 'lxml',
            'pillow': 'PIL',
            'tqdm': 'tqdm',
            'pyarrow': 'pyarrow',
        }

        results = {}
        for pip_name, import_name in deps.items():
            try:
                module = importlib.import_module(import_name)
            except ImportError:
                try:
                    install_package(pip_name, import_name)
                    module = importlib.import_module(import_name)
                except Exception as e:
                    logger.error(
                        f'Failed to install or import {pip_name}: {e}')
                    results[pip_name] = None
                    continue
            except Exception as e:
                logger.error(
                    f'Unexpected error when importing {pip_name}: {e}')
                results[pip_name] = None
                continue

            results[pip_name] = getattr(module, '__version__', 'no version')

        return results

    def _build_env(self, field: str, inherit: bool = False) -> Dict[str, str]:
        if inherit:
            env: Dict[str, str] = dict(os.environ)
            logger.warning(
                "It's not safe to inherit from the parent environment.")
        else:
            env: Dict[str, str] = {
                'INHERITED_FROM_LOCAL': 'False',
                'PATH': os.environ.get('PATH', ''),
                'HOME': os.environ.get('HOME', ''),
                'LANG': os.environ.get('LANG', ''),
            }

        if not self.tool_config or not hasattr(self.tool_config, field):
            return env
        env_cfg = getattr(self.tool_config, field)
        if isinstance(env_cfg, dict):
            items = env_cfg.items()
        else:
            try:
                items = env_cfg.items()
            except AttributeError:
                return env

        for key, value in items:
            if value is None:
                continue
            env[key] = str(value)
        return env

    async def connect(self) -> None:
        if self._initialized:
            return
        await self.kernel_session.start()
        self._initialized = True

    async def cleanup(self) -> None:
        if not self._initialized:
            return
        await self.kernel_session.stop()
        self._initialized = False

    async def get_tools(self) -> Dict[str, Any]:
        tools = {
            'code_executor': [
                Tool(
                    tool_name='notebook_executor',
                    server_name='code_executor',
                    description=
                    ('Execute Python code locally with state '
                     'persistence in a Jupyter kernel environment. Variables, imports, and '
                     'data are preserved across multiple calls within the same session. '
                     'Supports pandas, numpy, matplotlib, seaborn for data analysis. '
                     'Use print() to output results.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type':
                                'string',
                                'description':
                                ('Python code to execute in the notebook session. '
                                 'Can access previously defined variables. '
                                 'Use print() for output.')
                            },
                            'description': {
                                'type':
                                'string',
                                'description':
                                'Brief description of what the code does'
                            },
                            'timeout': {
                                'type': 'integer',
                                'minimum': 1,
                                'maximum': 600,
                                'description': 'Execution timeout in seconds',
                                'default': self._notebook_timeout
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='python_executor',
                    server_name='code_executor',
                    description=
                    ('Execute stateless Python code locally. '
                     'Each call runs in an isolated environment without '
                     'persisting context between invocations. '
                     'Supports pandas, numpy, matplotlib, seaborn, and other '
                     'libraries you need for data analysis. '
                     'Use print() to output results.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'code': {
                                'type': 'string',
                                'description': 'Python code to execute'
                            },
                            'description': {
                                'type':
                                'string',
                                'description':
                                'Brief description of what the code does'
                            },
                            'timeout': {
                                'type': 'integer',
                                'description': 'Execution timeout in seconds',
                                'default': self._python_timeout
                            }
                        },
                        'required': ['code'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='shell_executor',
                    server_name='code_executor',
                    description=('Execute shell commands locally using bash. '
                                 'Supports basic shell operations like ls, '
                                 'cd, mkdir, rm, etc. '),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'command': {
                                'type': 'string',
                                'description': 'Shell command to execute'
                            },
                            'timeout': {
                                'type': 'integer',
                                'description': 'Execution timeout in seconds',
                                'default': self._shell_timeout
                            }
                        },
                        'required': ['command'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='file_operation',
                    server_name='code_executor',
                    description=
                    'Perform file operations inside the local output directory',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'operation': {
                                'type':
                                'string',
                                'description':
                                'Type of file operation to perform',
                                'enum': [
                                    'create', 'read', 'write', 'delete',
                                    'list', 'exists'
                                ]
                            },
                            'file_path': {
                                'type': 'string',
                                'description': 'Path to the file or directory'
                            },
                            'content': {
                                'type':
                                'string',
                                'description':
                                'Content for write/create operations'
                            },
                            'encoding': {
                                'type': 'string',
                                'description': 'File encoding to use',
                                'default': 'utf-8'
                            }
                        },
                        'required': ['operation', 'file_path'],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='reset_executor',
                    server_name='code_executor',
                    description=
                    ('Restart the local ipykernel session to clear state. '
                     'All variables, imports, and session state will be cleared.'
                     ),
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False
                    }),
                Tool(
                    tool_name='get_executor_info',
                    server_name='code_executor',
                    description=
                    'Get information about the local execution environment.',
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False
                    }),
            ]
        }
        return {
            'code_executor': [
                t for t in tools['code_executor']
                if t['tool_name'] not in self.exclude_functions
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if not self._initialized:
            await self.connect()

        try:
            method = getattr(self, tool_name)
            return await method(**tool_args)
        except AttributeError:
            return json.dumps(
                {
                    'success': False,
                    'error': f'Unknown tool: {tool_name}'
                },
                ensure_ascii=False,
                indent=2)
        except Exception as exc:
            logger.error(
                f'Tool execution error ({tool_name}): {exc}', exc_info=True)
            return json.dumps(
                {
                    'success': False,
                    'error': f'Tool execution error: {exc}'
                },
                ensure_ascii=False,
                indent=2)

    async def notebook_executor(self,
                                code: str,
                                description: str = '',
                                timeout: Optional[int] = None) -> str:
        exec_timeout = timeout or self._notebook_timeout

        try:
            async with self._kernel_lock:
                result = await self.kernel_session.execute(code, exec_timeout)
        except Exception as exc:
            return json.dumps(
                {
                    'success': False,
                    'description': description,
                    'error': str(exc)
                },
                ensure_ascii=False,
                indent=2)

        error_payload = result.get('error')
        stderr = result.get('stderr') or ''
        if error_payload and error_payload.get('traceback'):
            stderr = '\n'.join(error_payload['traceback'])

        if error_payload:
            logger.warning(f'Code execution error: {stderr}')
        else:
            logger.info('Code executed successfully')

        return json.dumps(
            {
                'success': error_payload is None,
                'description': description,
                'output': result.get('output', ''),
                'error': stderr or None
            },
            ensure_ascii=False,
            indent=2)

    async def python_executor(self,
                              code: str,
                              description: str = '',
                              timeout: Optional[int] = None) -> str:
        exec_timeout = timeout or self._python_timeout

        def _exec_code():
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            globals_dict: Dict[str, Any] = {'__builtins__': __builtins__}
            locals_dict: Dict[str, Any] = {}
            with redirect_stdout(stdout_buffer), redirect_stderr(
                    stderr_buffer):
                exec(code, globals_dict, locals_dict)
            return stdout_buffer.getvalue(), stderr_buffer.getvalue()

        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_exec_code), timeout=exec_timeout)
        except asyncio.TimeoutError:
            return json.dumps(
                {
                    'success':
                    False,
                    'description':
                    description,
                    'error':
                    f'Python execution timed out after {exec_timeout} seconds'
                },
                ensure_ascii=False,
                indent=2)
        except Exception as exc:
            return json.dumps(
                {
                    'success': False,
                    'description': description,
                    'error': str(exc)
                },
                ensure_ascii=False,
                indent=2)

        if not stderr:
            logger.info('Python code executed successfully')
        else:
            logger.warning(f'Python code execution error: {stderr}')

        return json.dumps(
            {
                'success': not stderr,
                'description': description,
                'output': stdout.strip('\n'),
                'error': stderr.strip('\n') or None
            },
            ensure_ascii=False,
            indent=2)

    async def shell_executor(self,
                             command: str,
                             timeout: Optional[int] = None) -> str:
        exec_timeout = timeout or self._shell_timeout

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=ai_subprocess.PIPE,
                stderr=ai_subprocess.PIPE,
                cwd=str(self.output_dir),
                env=self.shell_env)
        except FileNotFoundError as exc:
            return json.dumps(
                {
                    'success': False,
                    'error': f'Shell not available: {exc}'
                },
                ensure_ascii=False,
                indent=2)

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=exec_timeout)
        except asyncio.TimeoutError:
            process.kill()
            try:
                await process.communicate()
            except Exception:  # noqa: B902
                pass
            return json.dumps(
                {
                    'success':
                    False,
                    'error':
                    f'Shell command timed out after {exec_timeout} seconds'
                },
                ensure_ascii=False,
                indent=2)

        stdout_text = _coerce_str(stdout).strip('\n')
        stderr_text = _coerce_str(stderr).strip('\n')
        success = process.returncode == 0
        return json.dumps(
            {
                'success': success,
                'output': stdout_text,
                'error': stderr_text or None,
                'return_code': process.returncode
            },
            ensure_ascii=False,
            indent=2)

    async def file_operation(self,
                             operation: str,
                             file_path: str,
                             content: Optional[str] = None,
                             encoding: Optional[str] = 'utf-8') -> str:
        try:
            target = self._resolve_path(file_path)
        except ValueError as exc:
            return json.dumps(
                {
                    'success': False,
                    'error': str(exc),
                    'file_path': file_path
                },
                ensure_ascii=False,
                indent=2)

        op = operation.lower()

        try:
            if op == 'create':
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)
                result = {
                    'success': True,
                    'file_path': str(target),
                    'message': 'File created'
                }
            elif op == 'read':
                data = target.read_text(encoding=encoding or 'utf-8')
                result = {
                    'success': True,
                    'file_path': str(target),
                    'output': data
                }
            elif op == 'write':
                if content is None:
                    raise ValueError('Content is required for write operation')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding=encoding or 'utf-8')
                result = {
                    'success': True,
                    'file_path': str(target),
                    'message': 'File written'
                }
            elif op == 'delete':
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                result = {
                    'success': True,
                    'file_path': str(target),
                    'message': 'Deleted successfully'
                }
            elif op == 'list':
                if not target.is_dir():
                    raise ValueError(
                        'List operation requires a directory path')
                entries = [{
                    'name':
                    child.name,
                    'is_dir':
                    child.is_dir(),
                    'size':
                    child.stat().st_size if child.is_file() else None
                } for child in sorted(target.iterdir())]
                result = {
                    'success': True,
                    'file_path': str(target),
                    'entries': entries
                }
            elif op == 'exists':
                result = {
                    'success': True,
                    'file_path': str(target),
                    'exists': target.exists()
                }
            else:
                raise ValueError(f'Unsupported file operation: {operation}')
        except Exception as exc:
            result = {
                'success': False,
                'file_path': str(target),
                'error': str(exc)
            }

        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    async def reset_executor(self) -> str:
        try:
            async with self._kernel_lock:
                await self.kernel_session.restart()
            return json.dumps(
                {
                    'success':
                    True,
                    'message':
                    'Local kernel session restarted. State has been cleared.'
                },
                ensure_ascii=False,
                indent=2)
        except Exception as exc:
            return json.dumps({'success': False, 'error': str(exc)}, ensure_ascii=False, indent=2)  # yapf: disable

    async def get_executor_info(self) -> str:
        info = {
            'success': True,
            'type': 'local_kernel',
            'working_dir': str(self.output_dir),
            'initialized': self._initialized,
            'execution_count': self.kernel_session.execution_count,
            'uptime_seconds': self.kernel_session.uptime,
        }
        return json.dumps(info, ensure_ascii=False, indent=2, default=str)

    def _resolve_path(self, file_path: str) -> Path:
        raw_path = Path(file_path).expanduser()
        if not raw_path.is_absolute():
            raw_path = (self.output_dir / raw_path).resolve()
        else:
            raw_path = raw_path.resolve()
        if not _is_relative_to(raw_path, self.output_dir):
            raise ValueError(
                'Access outside the output directory is not permitted')
        return raw_path
