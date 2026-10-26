import asyncio
import asyncio.subprocess as ai_subprocess
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.artifact_manager import ArtifactManager
from ms_agent.utils.workspace_context import WorkspaceContext

logger = get_logger()

#: Ambient variables a POSIX command may read without them carrying anything
#: the agent should not have. The environment is built as an allow-list rather
#: than inherited, so anything missing here is simply absent for every command
#: the agent runs — and an absent one is not a neutral default:
#:
#: * ``USER``/``LOGNAME`` unset makes ``git commit`` and anything deriving an
#:   identity from the environment fail or record the wrong author.
#: * ``TMPDIR`` unset sends every tool that wants scratch space to ``/tmp``,
#:   which is outside the workspace and therefore refused by the path policy —
#:   leaving the agent with nowhere to write a temporary file at all.
#: * ``SSL_CERT_FILE``/``REQUESTS_CA_BUNDLE`` unset breaks TLS for interpreters
#:   with no system trust store, so ``pip install`` fails to verify PyPI.
#: * The proxy variables are how a developer behind one reaches the network;
#:   dropping them turns every fetch into a timeout.
#:
#: Credentials are still NOT forwarded: no ``*_API_KEY``, ``*_TOKEN``,
#: ``AWS_*``, ``GITHUB_*`` or similar appears here, and the tool's own
#: ``shell_env`` config remains the way to pass one deliberately.
_POSIX_ENV_PASSTHROUGH = (
    'PATH',
    'HOME',
    'USER',
    'LOGNAME',
    'SHELL',
    'TMPDIR',
    'LANG',
    'LC_ALL',
    'LC_CTYPE',
    'TERM',
    'TZ',
    'SSL_CERT_FILE',
    'SSL_CERT_DIR',
    'REQUESTS_CA_BUNDLE',
    'CURL_CA_BUNDLE',
    'NODE_EXTRA_CA_CERTS',
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'ALL_PROXY',
    'NO_PROXY',
    'http_proxy',
    'https_proxy',
    'all_proxy',
    'no_proxy',
)

#: Set on every command the agent runs, unless the environment already says
#: otherwise. Nothing here changes what a command DOES — it changes what the
#: command assumes about who is reading.
#:
#: A pager is the sharp edge: ``git log`` or ``systemctl status`` hands its
#: output to ``less``, which waits for a keypress that will never come, and the
#: tool call sits there until it times out. Progress bars and colour codes are
#: milder, but they fill the result with control characters that cost context
#: and read as noise. ``AI_AGENT`` is a cross-vendor convention some tools
#: (``gh``) report in their User-Agent.
_AGENT_FRIENDLY_ENV = {
    'PAGER': 'cat',
    'GIT_PAGER': 'cat',
    'MANPAGER': 'cat',
    # -F quit if it all fits on one screen, -R keep colour, -X no alternate
    # screen. Needed because PAGER=cat only covers programs that CONSULT it;
    # anything invoking `less` directly would still sit waiting for a key.
    'LESS': '-FRX',
    'GIT_TERMINAL_PROMPT': '0',
    'GIT_MERGE_AUTOEDIT': 'no',
    'PIP_DISABLE_PIP_VERSION_CHECK': '1',
    'PIP_PROGRESS_BAR': 'off',
    'PYTHONUNBUFFERED': '1',
    'TQDM_DISABLE': '1',
    'DEBIAN_FRONTEND': 'noninteractive',
    'NO_COLOR': '1',
    'AI_AGENT': 'ms_agent',
}


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


class LocalCodeExecutionTool(ToolBase):
    """Run local commands in shell subprocesses and manage workspace files."""

    def __init__(self, config):
        super().__init__(config)
        self._ws = WorkspaceContext.from_config(config)
        self.output_dir = self._ws.root
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.tool_config = getattr(
            getattr(config, 'tools', None), 'code_executor', None)
        self._shell_timeout = getattr(self.tool_config, 'shell_timeout',
                                      60) if self.tool_config else 60

        self.shell_env = self._build_env('shell_env', inherit=False)
        self._initialized = False
        self._task_manager = None
        self._watcher_tasks: Set[asyncio.Task] = set()

        shell_cfg = getattr(self.tool_config, 'shell',
                            None) if self.tool_config else None
        max_kb = 256
        if shell_cfg and getattr(shell_cfg, 'max_output_kb', None):
            max_kb = int(shell_cfg.max_output_kb)
        self._artifacts = ArtifactManager(
            self._ws.root, max_combined_bytes=max_kb * 1024)

        self.exclude_func(
            getattr(getattr(config, 'tools', None), 'code_executor', None))
        if self._function_enabled('file_operation'):
            logger.warning(
                'file_operation is not suggested to be included in local code execution tool.'
            )

        logger.info('LocalCodeExecutionTool initialized')

    def _function_enabled(self, name: str) -> bool:
        if self.include_functions:
            return name in self.include_functions
        return name not in self.exclude_functions

    def set_task_manager(self, task_manager) -> None:
        """Attach process-wide TaskManager for background shell (see shell_executor)."""
        self._task_manager = task_manager

    def _build_env(self, field: str, inherit: bool = False) -> Dict[str, str]:
        if inherit:
            env: Dict[str, str] = dict(os.environ)
            logger.warning(
                "It's not safe to inherit from the parent environment.")
        else:
            env: Dict[str, str] = {
                'INHERITED_FROM_LOCAL': 'False',
            }
            for key in _POSIX_ENV_PASSTHROUGH:
                value = os.environ.get(key)
                if value is not None:
                    env[key] = value
            env.setdefault('PATH', '')
            # Set outright, NOT deferring to whatever the parent had. These
            # exist to undo settings made for a human at a terminal, so
            # inheriting them defeats the entire point: a developer's
            # `PAGER=less` is exactly the value that leaves `git log` waiting
            # for a keypress nobody will press. A deliberate choice still wins
            # — `tools.code_executor.shell_env` is applied after this.
            env.update(_AGENT_FRIENDLY_ENV)
            if os.name == 'nt':
                # ``create_subprocess_shell`` uses the native Windows command
                # processor. Keep the non-secret OS/user variables that cmd
                # and programs using temporary/profile directories require.
                for key in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
                            'TEMP', 'TMP', 'TMPDIR', 'USERPROFILE',
                            'HOMEDRIVE', 'HOMEPATH', 'USERNAME', 'APPDATA',
                            'LOCALAPPDATA', 'PROGRAMDATA', 'OS',
                            'PROCESSOR_ARCHITECTURE'):
                    value = os.environ.get(key)
                    if value is not None:
                        env[key] = value

        # The image supplies its system tool path separately from the SDK's
        # service PATH. Local installs keep their existing environment unless
        # the deployment explicitly configures this override.
        shell_path = os.environ.get('MS_AGENT_SHELL_PATH')
        if field == 'shell_env' and shell_path:
            env['PATH'] = shell_path
            for key in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV',
                        'PYTHONHOME', 'PYTHONPATH'):
                env.pop(key, None)

        env_cfg = getattr(self.tool_config, field, None)
        items = env_cfg.items() if hasattr(env_cfg, 'items') else ()
        for key, value in items:
            if value is None:
                continue
            env[key] = str(value)
        plugin_bins = getattr(self.tool_config, 'plugin_bin_paths',
                              None) if self.tool_config else None
        if plugin_bins:
            paths = [str(path) for path in plugin_bins if path]
            if paths:
                env['PATH'] = os.pathsep.join(paths + [env.get('PATH', '')])
        return env

    def _shell_environment_hint(self) -> str:
        path = self.shell_env.get('PATH', '')
        python = (
            shutil.which('python', path=path)
            or shutil.which('python3', path=path))
        pip = (
            shutil.which('pip', path=path) or shutil.which('pip3', path=path))
        return (
            f'Default Python: {python or "not found on PATH"}; '
            f'pip: {pip or "not found on PATH"}. '
            f'The SDK service runs with {sys.executable}. '
            'Do not install or upgrade ordinary task dependencies in the SDK '
            'service environment. Reuse an existing project environment, or '
            'create a project virtualenv when different package versions '
            'are needed. When installing into a container system Python with '
            'uv, use `uv pip install --system`; project virtualenvs do not '
            'need that flag.\n\n')

    async def connect(self) -> None:
        self._initialized = True

    async def cleanup(self) -> None:
        for t in list(self._watcher_tasks):
            if not t.done():
                t.cancel()
        self._watcher_tasks.clear()
        self._initialized = False

    async def _get_tools_inner(self) -> Dict[str, Any]:
        tools = {
            'code_executor': [
                Tool(
                    tool_name='shell_executor',
                    server_name='code_executor',
                    description=(
                        'Run a shell command.\n'
                        '\n' + self._shell_environment_hint() +
                        'Each call starts a NEW shell in the workspace root, '
                        f'which is {self._ws.root}. Changes to the working '
                        'directory, environment variables, and activated '
                        'virtualenv or conda environments do not carry over '
                        'between calls. Files persist, and command output is '
                        'returned to the conversation.\n'
                        '\n'
                        'So do each of those in the SAME call as the work '
                        'that needs it, chained with && — for example '
                        '`cd sub && ls`, or '
                        '`. .venv/bin/activate && pip install requests && '
                        'python -c "import requests"`. Prefer absolute paths '
                        'or a leading cd over assuming a directory from an '
                        'earlier call.\n'
                        '\n'
                        "Commands are checked by the agent's permission "
                        'policy; local processes are not sandboxed. '
                        'Reading credential files and running '
                        'code inline (python -c, heredocs) may require '
                        'approval. Large output is spilled to '
                        '.ms_agent/artifacts and the result says where. Use '
                        'run_in_background=true for a long command: it returns '
                        'a task_id immediately.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'command': {
                                'type': 'string',
                                'description': 'Shell command to execute'
                            },
                            'timeout': {
                                'type':
                                'integer',
                                'minimum':
                                1,
                                'maximum':
                                int(os.getenv('TOOL_CALL_TIMEOUT_MAX', '600')),
                                'description':
                                'Execution timeout in seconds (host-wide ceiling, default 600s; TOOL_CALL_TIMEOUT_MAX).',
                                'default':
                                self._shell_timeout
                            },
                            'run_in_background': {
                                'type': 'boolean',
                                'description':
                                'If true, start the command asynchronously and return task_id (requires TaskManager).',
                                'default': False,
                            },
                            '__call_id': {
                                'type':
                                'string',
                                'description':
                                'Optional correlation id (injected by host when supported).',
                            },
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
            ]
        }

        return tools

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if not self._initialized:
            await self.connect()

        try:
            method = getattr(self, tool_name)
            # Host runtimes may inject correlation metadata like ``__call_id``.
            # Normalize it to a plain kwarg so tool methods can accept it
            # without relying on Python dunder names (which are name-mangled
            # in class method signatures).
            call_args = dict(tool_args or {})
            if '__call_id' in call_args and 'call_id' not in call_args:
                call_args['call_id'] = call_args.pop('__call_id')
            return await method(**call_args)
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

    async def shell_executor(self,
                             command: str,
                             timeout: Optional[int] = None,
                             run_in_background: bool = False,
                             call_id: Optional[str] = None) -> str:
        exec_timeout = timeout or self._shell_timeout
        call_id = call_id or f'shell-{os.urandom(4).hex()}'

        # Handed to the shell verbatim. ``create_subprocess_shell`` already runs
        # it under ``/bin/sh -c`` (``cmd.exe`` on Windows), which understands
        # every compound form on its own, so there is nothing to pre-wrap.
        # Wrapping used to be conditional on the command CONTAINING a
        # metacharacter, and the wrapper was a LOGIN shell: adding a `;` to a
        # command re-ran the profile, which on macOS reorders PATH via
        # path_helper, so `python3 -V` and `python3 -V ; true` resolved to
        # different interpreters. Installing with one form and importing with
        # the other is then a ModuleNotFoundError with no visible cause.
        shell_cmd = command

        if run_in_background:
            if self._task_manager is None:
                return json.dumps(
                    {
                        'success':
                        False,
                        'error':
                        'run_in_background requires TaskManager (host must wire LLMAgent.task_manager).',
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            try:
                process = await asyncio.create_subprocess_shell(
                    shell_cmd,
                    stdout=ai_subprocess.PIPE,
                    stderr=ai_subprocess.PIPE,
                    cwd=str(self._ws.root),
                    env=self.shell_env,
                )
            except FileNotFoundError as exc:
                return json.dumps(
                    {
                        'success': False,
                        'error': f'Shell not available: {exc}'
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            task_id = self._task_manager.register(
                task_type='shell',
                tool_name='shell_executor',
                description=command[:200],
                proc=process,
            )

            async def _watcher() -> None:
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=exec_timeout)
                    stdout_text = _coerce_str(stdout).strip('\n')
                    stderr_text = _coerce_str(stderr).strip('\n')
                    success = process.returncode == 0
                    payload = {
                        'success': success,
                        'output': stdout_text,
                        'error': stderr_text or None,
                        'return_code': process.returncode,
                    }
                    text = self._artifacts.pack_json_shell_result(
                        tool_name='shell_executor',
                        call_id=task_id,
                        payload=payload,
                    )
                    await self._task_manager.complete(task_id, text)
                except asyncio.TimeoutError:
                    logger.warning(
                        f'Shell command timed out after {exec_timeout} seconds (task {task_id})'
                    )
                    try:
                        process.kill()
                        await process.communicate()
                    except Exception as exc:  # noqa: B902
                        logger.error(
                            f'Process cleanup failed: {exc}', exc_info=True)
                    if self._task_manager:
                        await self._task_manager.fail(
                            task_id,
                            f'Shell command timed out after {exec_timeout} seconds',
                        )
                except Exception as exc:  # noqa: B902
                    logger.error(f'Watcher task failed: {exc}', exc_info=True)
                    if self._task_manager:
                        await self._task_manager.fail(task_id, str(exc))

            t = asyncio.create_task(_watcher())
            self._watcher_tasks.add(t)
            t.add_done_callback(self._watcher_tasks.discard)

            return json.dumps(
                {
                    'status': 'async_launched',
                    'task_id': task_id,
                    'tool_name': 'shell_executor',
                    'call_id': call_id,
                },
                ensure_ascii=False,
                indent=2,
            )

        try:
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=ai_subprocess.PIPE,
                stderr=ai_subprocess.PIPE,
                cwd=str(self._ws.root),
                env=self.shell_env,
            )
        except FileNotFoundError as exc:
            return json.dumps(
                {
                    'success': False,
                    'error': f'Shell not available: {exc}'
                },
                ensure_ascii=False,
                indent=2,
            )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=exec_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                f'Shell command timed out after {exec_timeout} seconds (call {call_id})'
            )
            process.kill()
            try:
                await process.communicate()
            except Exception as exc:  # noqa: B902
                logger.error(f'Process cleanup failed: {exc}', exc_info=True)
            return json.dumps(
                {
                    'success':
                    False,
                    'error':
                    f'Shell command timed out after {exec_timeout} seconds'
                },
                ensure_ascii=False,
                indent=2,
            )

        stdout_text = _coerce_str(stdout).strip('\n')
        stderr_text = _coerce_str(stderr).strip('\n')
        success = process.returncode == 0
        payload = {
            'success': success,
            'output': stdout_text,
            'error': stderr_text or None,
            'return_code': process.returncode,
        }
        return self._artifacts.pack_json_shell_result(
            tool_name='shell_executor',
            call_id=call_id,
            payload=payload,
        )

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
