# Copyright (c) ModelScope Contributors. All rights reserved.
import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .base import CLICommand


def subparser_func(args):
    """ Function which will be called for a specific sub parser.
    """
    return UICMD(args)


class UICMD(CLICommand):
    """The webui command class."""

    name = 'ui'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        """Define args for the ui command."""
        parser: argparse.ArgumentParser = parsers.add_parser(UICMD.name)
        parser.add_argument(
            '--host',
            type=str,
            default='0.0.0.0',
            help='The server host to bind to.')
        parser.add_argument(
            '--port',
            type=int,
            default=7860,
            help='The server port to bind to.')
        parser.add_argument(
            '--reload',
            action='store_true',
            help='Enable auto-reload for development.')
        parser.add_argument(
            '--production',
            action='store_true',
            help='Run in production mode (serve built frontend).')
        parser.add_argument(
            '--no-browser',
            action='store_true',
            help='Do not automatically open browser.')
        parser.set_defaults(func=subparser_func)

    def execute(self):
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent.parent.parent
        webui_dir = project_root / 'webui'

        if not webui_dir.exists():
            import ms_agent
            ms_agent_path = Path(ms_agent.__file__).parent.parent
            webui_dir = ms_agent_path / 'webui'

        if not webui_dir.exists():
            webui_dir = Path.cwd() / 'webui'

        backend_dir = webui_dir / 'backend'
        frontend_dir = webui_dir / 'frontend'

        if not webui_dir.exists() or not backend_dir.exists():
            print('Error: WebUI directory not found.')
            sys.exit(1)

        frontend_dist = frontend_dir / 'dist'
        frontend_built = frontend_dist.exists() and (frontend_dist
                                                     / 'index.html').exists()

        if self.args.production and not frontend_built:
            print(
                'Error: Frontend not built. Please run "npm run build" in webui/frontend first.'
            )
            sys.exit(1)

        if not self.args.production and not frontend_built:
            if self._build_frontend(frontend_dir):
                frontend_built = True

        browser_host = 'localhost' if self.args.host == '0.0.0.0' else self.args.host
        browser_url = f'http://{browser_host}:{self.args.port}'

        backend_str = str(backend_dir)
        if backend_str not in sys.path:
            sys.path.insert(0, backend_str)

        original_argv = sys.argv
        original_cwd = os.getcwd()
        try:
            os.chdir(backend_dir)
            from main import main

            sys.argv = [
                'main.py',
                '--host',
                self.args.host,
                '--port',
                str(self.args.port),
            ]
            if self.args.reload:
                sys.argv.append('--reload')

            if not self.args.no_browser and frontend_built:

                def open_browser():
                    time.sleep(1.5)
                    webbrowser.open(browser_url)

                browser_thread = threading.Thread(
                    target=open_browser, daemon=True)
                browser_thread.start()

            main()
        except KeyboardInterrupt:
            print('\nShutting down...')
            sys.exit(0)
        except Exception as e:
            print(f'Error starting WebUI: {e}')
            import traceback
            traceback.print_exc()
            sys.exit(1)
        finally:
            sys.argv = original_argv
            os.chdir(original_cwd)

    def _build_frontend(self, frontend_dir: Path) -> bool:
        import subprocess

        try:
            subprocess.run(['npm', '--version'],
                           capture_output=True,
                           check=True,
                           timeout=5)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
                FileNotFoundError):
            return False

        node_modules = frontend_dir / 'node_modules'
        if not node_modules.exists():
            try:
                subprocess.run(['npm', 'install'],
                               cwd=frontend_dir,
                               check=True,
                               timeout=300,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                return False

        try:
            subprocess.run(['npm', 'run', 'build'],
                           cwd=frontend_dir,
                           check=True,
                           timeout=300,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
            return True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return False
