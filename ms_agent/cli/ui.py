# Copyright (c) ModelScope Contributors. All rights reserved.
"""Prepare the WebUI, then hand over to its shared SSR launcher."""
from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .base import CLICommand
from .ui_resources import UIError, find_webui, load_common, prepare_installed

DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8000
MIN_NODE_VERSION = (22, 22, 0)
MIN_UV_VERSION = (0, 5, 0)
IS_WINDOWS = os.name == 'nt'

#: Opt in to keeping only the traced SSR dependency closure instead of everything
#: `pnpm install` resolved. Deliberately not a CLI flag: the image sets it while
#: building, and the first preparation it triggers costs a full devDependency
#: install plus a tracing pass. Advertising it in `--help` would invite that onto
#: laptops, where the 430 MB it saves is a cache directory nobody ships.
TRACE_RUNTIME_ENV = 'MS_AGENT_WEBUI_TRACE_RUNTIME'


def _port_number(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('port must be an integer') from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('port must be between 1 and 65535')
    return port


def subparser_func(args):
    return UICMD(args)


class UICMD(CLICommand):
    name = 'ui'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers):
        parser = parsers.add_parser('ui', help='Start the WebUI (SSR and API)')
        parser.add_argument('--host', default=DEFAULT_HOST)
        parser.add_argument(
            '--port',
            type=_port_number,
            help='Public port (default: a free port starting at 8000)')
        parser.add_argument(
            '--backend-port',
            type=_port_number,
            help='Internal API port (default: next free port)')
        parser.add_argument('--no-browser', action='store_true')
        parser.add_argument(
            '--skip-install',
            action='store_true',
            help='Do not download or synchronize dependencies')
        parser.add_argument(
            '--production',
            action='store_true',
            help='Compatibility alias for the default SSR mode')
        parser.add_argument(
            '--reload',
            action='store_true',
            help='Reserved; use the documented development commands')
        parser.add_argument(
            '--prepare-only',
            action='store_true',
            help='Prepare resources and dependencies, then exit')
        parser.add_argument('--startup-timeout', type=float, default=120.0)
        parser.set_defaults(func=subparser_func)

    def execute(self):
        try:
            if self.args.reload:
                raise UIError(
                    '--reload is not supported by the unified SSR launcher. '
                    'Use the backend dev command and pnpm dev as described in webui/README.md.'
                )
            if sys.version_info < (3, 12):
                raise UIError('The WebUI requires Python 3.12 or newer')
            if not math.isfinite(self.args.startup_timeout
                                 ) or self.args.startup_timeout <= 0:
                raise UIError('--startup-timeout must be positive and finite')
            webui, installed = find_webui()
            common = load_common(webui)
            # These shared helpers are imported without loading the API or SDK state.
            from app.processes import interruptible

            with interruptible():
                host = self.args.host.strip().removeprefix('[').removesuffix(
                    ']')
                if not host:
                    raise UIError('--host cannot be empty')
                if not self.args.prepare_only:
                    ports = common.select_ports(host, self.args.port,
                                                self.args.backend_port)
                node = _require_executable('node')
                _check_tool_versions({'node': node})
                node_version = _read_semantic_version(node, '--version',
                                                      'Node.js')

                def install_node(frontend, production=False):
                    pnpm = _require_executable('pnpm')
                    _check_tool_versions({
                        'node': node,
                        'pnpm': pnpm
                    }, frontend)
                    command = [pnpm, 'install', '--frozen-lockfile']
                    if production:
                        command.append('--prod')
                    print(
                        '[setup] Preparing WebUI Node dependencies...',
                        flush=True)
                    _run_setup(command, frontend,
                               'Node dependency installation')

                def build_frontend(frontend):
                    pnpm = _require_executable('pnpm')
                    _check_tool_versions({
                        'node': node,
                        'pnpm': pnpm
                    }, frontend)
                    print(
                        '[setup] Building WebUI (including generated CSS)...',
                        flush=True)
                    _run_setup([pnpm, 'build'], frontend, 'frontend build')

                def trace_runtime(frontend):
                    pnpm = _require_executable('pnpm')
                    _check_tool_versions({
                        'node': node,
                        'pnpm': pnpm
                    }, frontend)
                    print(
                        '[setup] Tracing WebUI runtime dependencies...',
                        flush=True)
                    _run_setup(
                        [pnpm, 'exec', 'tsx', 'scripts/traceRuntime.ts'],
                        frontend, 'runtime dependency tracing')

                if installed:
                    tracing = os.environ.get(TRACE_RUNTIME_ENV) == '1'
                    webui = prepare_installed(
                        webui,
                        common,
                        node_version,
                        skip_install=self.args.skip_install,
                        install_node=install_node,
                        build_frontend=build_frontend,
                        trace_runtime=trace_runtime if tracing else None)
                    python = Path(sys.executable)
                else:
                    backend = webui / 'backend'
                    python = backend / '.venv' / ('Scripts/python.exe' if
                                                  IS_WINDOWS else 'bin/python')
                    if not self.args.skip_install:
                        uv = _require_executable('uv')
                        _check_tool_versions({'node': node, 'uv': uv})
                        env = os.environ.copy()
                        env['UV_PROJECT_ENVIRONMENT'] = str(backend / '.venv')
                        print(
                            '[setup] Checking WebUI Python dependencies...',
                            flush=True)
                        _run_setup(
                            [uv, 'sync', '--locked', '--no-dev', '--inexact'],
                            backend,
                            'Python dependency synchronization',
                            env=env)
                        install_node(webui / 'frontend')
                    if not python.is_file():
                        raise UIError(
                            'Missing WebUI backend environment; run without --skip-install'
                        )
                    if not (webui / 'frontend/node_modules').is_dir():
                        raise UIError(
                            'Missing frontend dependencies; run without --skip-install'
                        )
                    try:
                        common.validate_build(webui / 'frontend')
                    except common.BuildError:
                        build_frontend(webui / 'frontend')
                        common.validate_build(webui / 'frontend')
                if self.args.prepare_only:
                    print(f'WebUI prepared: {webui}', flush=True)
                    return
                arguments = [
                    '--host', host, '--port',
                    str(ports[0]), '--backend-port',
                    str(ports[1]), '--startup-timeout',
                    str(self.args.startup_timeout)
                ]
                if self.args.no_browser:
                    arguments.append('--no-open')
            _exec_launcher(python, webui, arguments, installed=installed)
        except KeyboardInterrupt:
            print('WebUI preparation stopped.', flush=True)
        except (UIError, OSError, RuntimeError, subprocess.SubprocessError,
                ValueError) as exc:
            print(f'Cannot start WebUI: {exc}', file=sys.stderr, flush=True)
            raise SystemExit(1) from None


def _exec_launcher(python, webui, arguments, *, installed):
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    if installed:
        env['MS_AGENT_WEBUI_INSTALLED'] = '1'
    else:
        env.pop('MS_AGENT_WEBUI_INSTALLED', None)
    os.chdir(webui / 'backend')
    # Replace the preparation process: the shared launcher owns all service
    # supervision and signal handling, without a second SDK supervisor.
    os.execve(
        str(python), [str(python), '-m', 'app.launcher', *arguments], env)


def _requires_windows_shell(executable):
    return IS_WINDOWS and Path(executable).suffix.lower() in {'.bat', '.cmd'}


def _run_setup(command, cwd, label, env=None):
    from app.processes import _spawn, _terminate_process_tree

    process = _spawn(
        command, cwd=cwd, env=env, shell=_requires_windows_shell(command[0]))
    try:
        code = process.wait()
        if code:
            raise UIError(f'{label} failed with exit code {code}')
    except BaseException:
        _terminate_process_tree(process)
        raise


def _require_executable(name: str) -> str:
    """Resolve a required executable, including ``.cmd``/``.exe`` on Windows."""
    executable = shutil.which(name)
    if executable:
        return executable

    install_hints = {
        'uv': 'Install uv from https://docs.astral.sh/uv/.',
        'node': 'Install Node.js 22.22.0 or newer from https://nodejs.org/.',
        'pnpm': 'Install it with npm install --global pnpm@10.17.1.',
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
    node_version = _read_semantic_version(tools['node'], '--version',
                                          'Node.js')
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
                f'"npm install --global pnpm@10.17.1", then check '
                f'"pnpm --version" in the frontend directory.')


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
        raise UIError(
            f'Could not determine the {label} version: {exc}') from exc

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
