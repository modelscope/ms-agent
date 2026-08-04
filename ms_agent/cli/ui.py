# Copyright (c) ModelScope Contributors. All rights reserved.
"""Launch the source-checkout WebUI development stack."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base import CLICommand


DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 7860
DEFAULT_BACKEND_PORT = 8000
DEFAULT_STARTUP_TIMEOUT = 120.0
IS_WINDOWS = os.name == 'nt'
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP',
                                   0x00000200)
CTRL_BREAK_EVENT = getattr(signal, 'CTRL_BREAK_EVENT', 1)
MIN_NODE_VERSION = (22, 22, 0)
# The floor is set by the flags _ensure_dependencies passes: `--locked` and
# `--inexact`. Probed by the launcher rather than delegated to
# `[tool.uv] required-version` alone, because uv's own refusal reaches us only
# as an exit code from _run_setup — with no version and no path in the message,
# which is exactly the ambiguity this check exists to remove.
MIN_UV_VERSION = (0, 5, 0)

# Health checks target loopback, so they must never traverse a proxy. The
# default opener installs ProxyHandler(getproxies()), and on macOS getproxies()
# also reads System Configuration — so an active VPN or a debugging proxy
# applies with no environment variable set, and 127.0.0.1 is NOT bypassed unless
# it is explicitly listed in no_proxy. The symptom is brutal: both servers come
# up healthy, every probe is routed away from them, and after the startup
# timeout the launcher kills two working processes.
_LOOPBACK_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))


class UIError(RuntimeError):
    """A user-facing WebUI launcher error."""


def _port_number(value: str) -> int:
    """Parse a TCP port early enough for argparse to show a concise error."""
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('port must be between 1 and 65535')
    return port


def subparser_func(args):
    """Build the command object selected by argparse."""
    return UICMD(args)


class UICMD(CLICommand):
    """Start FastAPI and the React Router development server together."""

    name = 'ui'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        """Define ``ms-agent ui`` arguments."""
        parser: argparse.ArgumentParser = parsers.add_parser(UICMD.name)
        parser.add_argument(
            '--host',
            type=str,
            default=DEFAULT_HOST,
            help='Public frontend host (default: 127.0.0.1).')
        parser.add_argument(
            '--port',
            type=_port_number,
            default=DEFAULT_PORT,
            help='Public frontend port (default: 7860).')
        parser.add_argument(
            '--backend-port',
            type=_port_number,
            default=DEFAULT_BACKEND_PORT,
            help='Internal FastAPI port (default: 8000).')
        parser.add_argument(
            '--reload',
            action='store_true',
            help='Reload the Python backend when its source changes.')
        parser.add_argument(
            '--mock',
            action='store_true',
            help='Use the in-memory mock backend instead of ms-agent.')
        parser.add_argument(
            '--skip-install',
            action='store_true',
            help='Do not install missing project-local dependencies.')
        parser.add_argument(
            '--production',
            action='store_true',
            help='Reserved; production SSR is not supported by this launcher.')
        parser.add_argument(
            '--no-browser',
            action='store_true',
            help='Do not automatically open the browser.')
        parser.set_defaults(func=subparser_func)

    def execute(self):
        processes: List[Tuple[str, subprocess.Popen]] = []
        exit_code = 0
        previous_signal_handlers = {}

        # A service manager normally stops the launcher with SIGTERM rather
        # than Ctrl+C; a POSIX terminal may send SIGHUP when it closes.
        # Translate both into the same graceful path so neither child process
        # tree is left behind.
        for signal_name in ('SIGTERM', 'SIGHUP'):
            shutdown_signal = getattr(signal, signal_name, None)
            if shutdown_signal is None:
                continue
            previous_signal_handlers[shutdown_signal] = signal.getsignal(
                shutdown_signal)
            signal.signal(shutdown_signal, _raise_keyboard_interrupt)

        try:
            if self.args.production:
                raise UIError(
                    '--production is not supported by the source WebUI '
                    'launcher. Run without it for local development.')
            if self.args.port == self.args.backend_port:
                raise UIError(
                    'The frontend and backend ports must be different.')

            frontend_host = _bind_host(self.args.host)
            if not frontend_host:
                raise UIError('The frontend host cannot be empty.')

            webui_dir = _find_webui_dir()
            backend_dir = webui_dir / 'backend'
            frontend_dir = webui_dir / 'frontend'

            tools = {'node': _require_executable('node')}
            if not self.args.skip_install:
                tools.update({
                    'uv': _require_executable('uv'),
                    'pnpm': _require_executable('pnpm'),
                })
            _check_tool_versions(tools, frontend_dir=frontend_dir)
            # Claim both ports BEFORE mutating anything. Dependency sync takes
            # seconds and writes to .venv / node_modules; discovering the port
            # clash only after that (as a child's exit code) wasted the work and
            # reported "backend exited unexpectedly" instead of naming the port.
            _check_ports_available(frontend_host, self.args.port,
                                   self.args.backend_port)
            _ensure_dependencies(
                backend_dir,
                frontend_dir,
                tools,
                skip_install=self.args.skip_install,
            )

            backend_url = f'http://127.0.0.1:{self.args.backend_port}'
            public_url = _public_url(frontend_host, self.args.port)

            print('MS-Agent WebUI - local development mode', flush=True)
            print(f'  Frontend: {public_url}', flush=True)
            print(f'  Backend:  {backend_url}', flush=True)
            if not _is_loopback_host(frontend_host):
                print(
                    '  Warning: the frontend development server is exposed '
                    'beyond this machine.',
                    flush=True,
                )

            backend = _start_backend(
                backend_dir,
                port=self.args.backend_port,
                reload=self.args.reload,
                mock=self.args.mock,
            )
            processes.append(('backend', backend))
            _wait_for_http(
                f'{backend_url}/api/health',
                processes,
                timeout=DEFAULT_STARTUP_TIMEOUT,
                label='backend',
            )

            frontend = _start_frontend(
                frontend_dir,
                tools['node'],
                host=frontend_host,
                port=self.args.port,
                backend_url=backend_url,
            )
            processes.append(('frontend', frontend))
            _wait_for_http(
                public_url,
                processes,
                timeout=DEFAULT_STARTUP_TIMEOUT,
                label='frontend',
            )

            print(f'WebUI ready: {public_url}', flush=True)
            if not self.args.no_browser:
                try:
                    if not webbrowser.open(public_url):
                        print(
                            f'Could not open a browser automatically. Open '
                            f'{public_url} manually.',
                            file=sys.stderr,
                        )
                except (webbrowser.Error, OSError) as exc:
                    print(
                        f'Could not open a browser automatically: {exc}. '
                        f'Open {public_url} manually.',
                        file=sys.stderr,
                    )

            _monitor_processes(processes)
        except KeyboardInterrupt:
            print('\nShutting down WebUI...', flush=True)
        except UIError as exc:
            print(f'Error starting WebUI: {exc}', file=sys.stderr, flush=True)
            exit_code = 1
        finally:
            for _name, process in reversed(processes):
                _terminate_process_tree(process)
            for shutdown_signal, previous in previous_signal_handlers.items():
                # getsignal() returns None when the handler was installed from
                # C (an embedding host), and signal.signal(sig, None) raises
                # TypeError — inside `finally` that would replace the real
                # exception with a traceback about signal plumbing.
                if previous is None:
                    continue
                signal.signal(shutdown_signal, previous)

        if exit_code:
            raise SystemExit(exit_code)


def _find_webui_dir() -> Path:
    """Find a complete WebUI tree in source and future package layouts."""
    candidates = [Path(__file__).resolve().parents[2] / 'webui']

    try:
        import ms_agent

        candidates.append(Path(ms_agent.__file__).resolve().parent / 'webui')
    except (ImportError, TypeError):
        pass

    candidates.append(Path.cwd() / 'webui')

    checked: List[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        marker_paths = (
            resolved / 'backend' / 'app' / 'main.py',
            resolved / 'backend' / 'pyproject.toml',
            resolved / 'frontend' / 'package.json',
            resolved / 'frontend' / 'vite.config.ts',
        )
        if all(path.is_file() for path in marker_paths):
            return resolved
        if str(resolved) not in checked:
            checked.append(str(resolved))

    raise UIError('WebUI source tree not found. Checked: ' +
                  ', '.join(checked))


def _port_in_use(host: str, port: int) -> bool:
    """Whether *host:port* is already bound (best effort, non-intrusive)."""
    for family, socktype, proto, _canon, addr in socket.getaddrinfo(
            host or '127.0.0.1', port, type=socket.SOCK_STREAM):
        with socket.socket(family, socktype, proto) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(addr)
            except OSError:
                return True
    return False


def _check_ports_available(frontend_host: str, frontend_port: int,
                           backend_port: int) -> None:
    """Fail early, and name the port — the most common cause is a second run."""
    busy = []
    if _port_in_use(frontend_host, frontend_port):
        busy.append(f'frontend {frontend_host}:{frontend_port}')
    # The backend is always bound to loopback (see _start_backend).
    if _port_in_use('127.0.0.1', backend_port):
        busy.append(f'backend 127.0.0.1:{backend_port}')
    if busy:
        raise UIError(
            'Port already in use: ' + ', '.join(busy) +
            '. Another "ms-agent ui" is probably still running — stop it, or '
            'pass different --port / --backend-port values.')


def _require_executable(name: str) -> str:
    """Resolve a required executable, including ``.cmd``/``.exe`` on Windows."""
    executable = shutil.which(name)
    if executable:
        return executable

    install_hints = {
        'uv': 'Install uv from https://docs.astral.sh/uv/.',
        'node': 'Install Node.js 22.22.0 or newer from https://nodejs.org/.',
        'pnpm': 'Install pnpm 10 (for example: corepack enable).',
    }
    raise UIError(f'Required command "{name}" was not found. '
                  f'{install_hints.get(name, "Install it and retry.")}')


def _check_tool_versions(tools: Dict[str, str],
                         frontend_dir: Optional[Path] = None) -> None:
    """Gate on tool versions, always naming the executable that was measured.

    Printing the resolved path matters more than the version: the common failure
    is "I installed it into this environment but PATH resolved something else",
    which an unadorned version number cannot distinguish.
    """
    node_version = _read_semantic_version(tools['node'], '--version', 'Node.js')
    if node_version < MIN_NODE_VERSION:
        required = '.'.join(str(part) for part in MIN_NODE_VERSION)
        actual = '.'.join(str(part) for part in node_version)
        raise UIError(
            f'Node.js {required} or newer is required by React Router 8 '
            f'(found {actual} at {tools["node"]}).')

    if 'uv' in tools:
        uv_version = _read_semantic_version(tools['uv'], '--version', 'uv')
        if uv_version < MIN_UV_VERSION:
            required = '.'.join(str(part) for part in MIN_UV_VERSION)
            actual = '.'.join(str(part) for part in uv_version)
            raise UIError(
                f'uv {required} or newer is required (found {actual} at '
                f'{tools["uv"]}). If you installed a newer uv into this '
                f'environment, an older one is still earlier on PATH — check '
                f'with "command -v uv".')

    if 'pnpm' in tools:
        # Measure pnpm inside webui/frontend: `packageManager` in its
        # package.json makes pnpm self-manage, so the binary that actually runs
        # `pnpm install` there may differ from the one first on PATH. Probing
        # from an arbitrary cwd validates the wrong executable.
        pnpm_version = _read_semantic_version(
            tools['pnpm'], '--version', 'pnpm', cwd=frontend_dir)
        if pnpm_version[0] != 10:
            actual = '.'.join(str(part) for part in pnpm_version)
            raise UIError(
                f'pnpm 10.x is required by this WebUI (found {actual} at '
                f'{tools["pnpm"]}). Install it with '
                f'"npm install --global --prefix \\"$CONDA_PREFIX\\" '
                f'pnpm@10.17.1" (or "corepack prepare pnpm@10.17.1 --activate" '
                f'on Node < 25, where corepack is still bundled), then verify '
                f'with "command -v pnpm".')


def _read_semantic_version(executable: str,
                           flag: str,
                           label: str,
                           cwd: Optional[Path] = None) -> Tuple[int, int, int]:
    run_kwargs: Dict[str, Any] = {}
    if cwd is not None:
        run_kwargs['cwd'] = str(cwd)
    if _requires_windows_shell(executable):
        # Corepack commonly exposes pnpm as pnpm.cmd. CreateProcess cannot
        # execute a command script directly, so let subprocess quote it for
        # the native command processor. All arguments here are launcher-owned.
        run_kwargs['shell'] = True
    try:
        result = subprocess.run(
            [executable, flag],
            capture_output=True,
            check=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
            **run_kwargs,
        )
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        raise UIError(f'Could not determine the {label} version: {exc}') from exc

    return _parse_semantic_version(result.stdout, label, executable)


#: A version at the very start of a line: ``v22.22.0`` / ``10.17.1``.
_VERSION_BARE = re.compile(r'^v?(\d+)\.(\d+)(?:\.(\d+))?\b')
#: A version after a single leading token: ``uv 0.12.1 (a6042f67 2026-03-24)``.
_VERSION_AFTER_NAME = re.compile(r'^\S+\s+v?(\d+)\.(\d+)(?:\.(\d+))?\b')


def _parse_semantic_version(output: str, label: str,
                            executable: str) -> Tuple[int, int, int]:
    """Read the tool's version, ignoring any preamble noise.

    Searching the whole buffer for the first dotted number is wrong: tools
    prepend notices (Node deprecation warnings, corepack "about to download
    pnpm-10.17.1.tgz", mise/conda preambles, uv "a newer version is available",
    and on Windows whatever cmd.exe AutoRun echoes). Matching that noise yields
    a *confident wrong version* — worse than failing to parse, because the
    caller then rejects a perfectly good toolchain citing a number the user
    never installed.

    Two passes over the lines, last first: a bare version wins outright, and
    only if no line carries one do we accept ``<name> <version>`` (uv's shape).
    Ordering the passes this way keeps a trailing "Update available 11.0.0"
    notice from beating the real version on the line above it.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for pattern in (_VERSION_BARE, _VERSION_AFTER_NAME):
        for line in reversed(lines):
            match = pattern.match(line)
            if match:
                return tuple(int(part or 0) for part in match.groups())
    raise UIError(f'Could not parse the {label} version from {executable}: '
                  f'{output!r}')


def _ensure_dependencies(
    backend_dir: Path,
    frontend_dir: Path,
    tools: Dict[str, str],
    skip_install: bool,
) -> None:
    """Synchronize local environments without changing either lockfile."""
    backend_missing = not (backend_dir / '.venv').is_dir()
    frontend_missing = not (frontend_dir / 'node_modules').is_dir()

    missing = []
    if backend_missing:
        missing.append('webui/backend/.venv')
    if frontend_missing:
        missing.append('webui/frontend/node_modules')
    if missing and skip_install:
        raise UIError(
            'Missing local dependencies: ' + ', '.join(missing) +
            '. Remove --skip-install or install them manually.')
    if skip_install:
        return

    action = 'Installing' if backend_missing else 'Checking'
    print(f'[setup] {action} WebUI backend dependencies...', flush=True)
    backend_env = _child_environment()
    backend_env['UV_PROJECT_ENVIRONMENT'] = str(backend_dir / '.venv')
    # --locked, not --frozen: `--frozen` means "use the lockfile WITHOUT
    # checking that it is up to date", which is the opposite of pnpm's
    # identically-named --frozen-lockfile. Since `ms-agent` is a path dependency
    # whose requirements are dynamic (setup.py parses requirements/*.txt), a
    # stale lock would sync a venv missing a new dependency and only surface as
    # an ImportError inside the worker, after the 120s health-check wait.
    # --inexact: uv syncs exactly by default and would UNINSTALL anything not in
    # the resolution — including the dev group this command excludes. Without it
    # every launch removes pytest, so `webui/backend`'s own test suite cannot
    # survive a single `ms-agent ui`.
    _run_setup(
        [tools['uv'], 'sync', '--locked', '--no-dev', '--inexact'],
        cwd=backend_dir,
        label='backend dependency synchronization',
        env=backend_env,
    )

    action = 'Installing' if frontend_missing else 'Checking'
    print(f'[setup] {action} WebUI frontend dependencies...', flush=True)
    _run_setup(
        [tools['pnpm'], 'install', '--frozen-lockfile'],
        cwd=frontend_dir,
        label='frontend dependency synchronization',
    )


def _run_setup(command: List[str],
               cwd: Path,
               label: str,
               env: Optional[Dict[str, str]] = None) -> None:
    process = _spawn(
        command,
        cwd=cwd,
        env=env,
        shell=_requires_windows_shell(command[0]),
    )
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        _terminate_process_tree(process)
        raise
    except OSError as exc:
        # Reap before surfacing: this process was never added to `processes`, so
        # execute()'s finally cannot reach it and it would outlive the launcher.
        _terminate_process_tree(process)
        raise UIError(f'{label} failed: {exc}') from exc
    if return_code:
        _terminate_process_tree(process)
        raise UIError(f'{label} failed with exit code {return_code}.')


def _child_environment() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault('PYTHONUTF8', '1')
    env.setdefault('PYTHONIOENCODING', 'utf-8')
    return env


def _requires_windows_shell(executable: str) -> bool:
    """Return whether an executable is a Windows command script."""
    return IS_WINDOWS and Path(executable).suffix.lower() in {'.bat', '.cmd'}


def _raise_keyboard_interrupt(_signum, _frame) -> None:
    """Route a termination signal through ``execute``'s cleanup block."""
    raise KeyboardInterrupt


def _start_backend(
    backend_dir: Path,
    port: int,
    reload: bool,
    mock: bool,
) -> subprocess.Popen:
    env = _child_environment()
    env.update({
        'HOST': '127.0.0.1',
        'PORT': str(port),
        'AGENT_BACKEND': 'mock' if mock else 'ms_agent',
    })
    python_dir = 'Scripts' if IS_WINDOWS else 'bin'
    python_name = 'python.exe' if IS_WINDOWS else 'python'
    python = backend_dir / '.venv' / python_dir / python_name
    if not python.is_file():
        raise UIError(
            f'WebUI backend interpreter not found at {python}. '
            'Run without --skip-install to repair the environment.')

    command = [
        str(python),
        '-m',
        'uvicorn',
        'app.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        str(port),
    ]
    if reload:
        command.extend(['--reload', '--reload-dir', 'app'])
    return _spawn(
        command,
        cwd=backend_dir,
        env=env,
    )


def _start_frontend(
    frontend_dir: Path,
    node: str,
    host: str,
    port: int,
    backend_url: str,
) -> subprocess.Popen:
    env = _child_environment()
    env['API_BASE_URL'] = backend_url
    react_router = (
        frontend_dir / 'node_modules' / '@react-router' / 'dev' / 'bin.cjs')
    if not react_router.is_file():
        raise UIError(
            f'React Router CLI not found at {react_router}. '
            'Run without --skip-install to repair the environment.')
    return _spawn(
        [
            node,
            str(react_router),
            'dev',
            '--host',
            host,
            '--port',
            str(port),
            '--strictPort',
        ],
        cwd=frontend_dir,
        env=env,
    )


def _spawn(command: List[str],
           cwd: Path,
           env: Optional[Dict[str, str]],
           shell: bool = False) -> subprocess.Popen:
    kwargs = {
        'cwd': str(cwd),
        'env': env,
    }
    if shell:
        kwargs['shell'] = True
    if IS_WINDOWS:
        kwargs['creationflags'] = CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True

    try:
        return subprocess.Popen(command, **kwargs)
    except OSError as exc:
        raise UIError(f'Could not start {Path(command[0]).name}: {exc}') from exc


def _wait_for_http(
    url: str,
    processes: Iterable[Tuple[str, subprocess.Popen]],
    timeout: float,
    label: str,
) -> None:
    deadline = time.monotonic() + timeout
    last_error = 'not ready'

    while time.monotonic() < deadline:
        for process_name, process in processes:
            return_code = process.poll()
            if return_code is not None:
                raise UIError(
                    f'{process_name} exited before {label} was ready '
                    f'(exit code {return_code}).')

        try:
            request = urllib.request.Request(
                url, headers={'User-Agent': 'ms-agent-ui-launcher'})
            with _LOOPBACK_OPENER.open(request, timeout=2) as response:
                if response.status == 200:
                    return
                last_error = f'HTTP {response.status}'
        except urllib.error.HTTPError as exc:
            last_error = f'HTTP {exc.code}'
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)

        time.sleep(0.25)

    raise UIError(
        f'Timed out waiting for {label} at {url} ({last_error}).')


def _monitor_processes(
        processes: Iterable[Tuple[str, subprocess.Popen]]) -> None:
    while True:
        for process_name, process in processes:
            return_code = process.poll()
            if return_code is not None:
                raise UIError(
                    f'{process_name} exited unexpectedly '
                    f'(exit code {return_code}).')
        time.sleep(0.25)


def _terminate_process_tree(process: subprocess.Popen,
                            grace_seconds: float = 5.0) -> None:
    """Stop a launcher child and its descendants cross-platform."""
    leader_running = process.poll() is None

    if IS_WINDOWS:
        if not leader_running:
            # Best effort: taskkill can still find the tree during the short
            # interval before Windows finishes re-parenting descendants.
            if not _taskkill(process.pid, force=True):
                _warn_cleanup(process.pid)
            return
        try:
            process.send_signal(CTRL_BREAK_EVENT)
        except OSError:
            if not _taskkill(process.pid, force=True):
                _warn_cleanup(process.pid)
            try:
                process.wait(timeout=grace_seconds)
            except (OSError, subprocess.TimeoutExpired):
                _warn_cleanup(process.pid)
            return
    else:
        # A process-group leader may already have exited while descendants are
        # still alive. killpg remains valid in that state, so do not return
        # merely because Popen.poll() has a return code.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            if leader_running:
                try:
                    process.terminate()
                except OSError:
                    pass
        if not leader_running and _wait_for_posix_group_exit(
                process.pid, grace_seconds):
            return
        if not leader_running:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            if not _wait_for_posix_group_exit(process.pid, grace_seconds):
                _warn_cleanup(process.pid)
            return

    try:
        process.wait(timeout=grace_seconds)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    if IS_WINDOWS:
        if not _taskkill(process.pid, force=True):
            _warn_cleanup(process.pid)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass

    try:
        process.wait(timeout=grace_seconds)
    except (OSError, subprocess.TimeoutExpired):
        _warn_cleanup(process.pid)


def _taskkill(pid: int, force: bool) -> bool:
    command = ['taskkill', '/PID', str(pid), '/T']
    if force:
        command.append('/F')
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _warn_cleanup(pid: int) -> None:
    print(
        f'Warning: could not confirm cleanup of process tree {pid}. '
        'Check for remaining Python/Node processes.',
        file=sys.stderr,
        flush=True,
    )


def _wait_for_posix_group_exit(pid: int, timeout: float) -> bool:
    """Wait until a POSIX process group no longer has live members."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        except OSError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _bind_host(host: str) -> str:
    """Normalize bracketed IPv6 URL literals for a server bind argument."""
    normalized = host.strip()
    if normalized.startswith('[') and normalized.endswith(']'):
        return normalized[1:-1]
    return normalized


def _is_loopback_host(host: str) -> bool:
    return host.strip().lower() in {
        '127.0.0.1',
        '::1',
        '[::1]',
        'localhost',
    }


def _public_url(host: str, port: int) -> str:
    normalized = host.strip()
    if normalized == '0.0.0.0':
        normalized = '127.0.0.1'
    elif normalized in {'::', '[::]'}:
        normalized = '::1'
    if ':' in normalized and not normalized.startswith('['):
        normalized = f'[{normalized}]'
    return f'http://{normalized}:{port}'
