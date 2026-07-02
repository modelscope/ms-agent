# Copyright (c) ModelScope Contributors. All rights reserved.
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from ms_agent.plugins.config_manager import PluginConfigManager
from ms_agent.plugins.installer import PluginInstaller, UnsupportedPluginSource
from ms_agent.plugins.runtime import PluginRuntime
from ms_agent.utils import get_logger

from .base import CLICommand

logger = get_logger()


def subparser_func(args):
    return PluginCMD(args)


class PluginCMD(CLICommand):
    """Install and manage MS-Agent community plugins."""

    name = 'plugin'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            PluginCMD.name,
            help='Install and manage plugins',
        )
        subparsers = parser.add_subparsers(
            dest='plugin_command',
            required=True,
            help='Plugin management commands',
        )

        install = subparsers.add_parser(
            'install',
            help='Install a plugin from local path, github://, modelscope://, or marketplace alias',
        )
        install.add_argument(
            'source',
            help=(
                'Plugin source, e.g. ./path, github://org/repo@ref#subdir, '
                'or hookify@claude-plugins-official'
            ),
        )
        install.add_argument(
            '--scope',
            choices=('global', 'project'),
            default='global',
            help='Install scope (default: global)',
        )
        install.add_argument(
            '--project-path',
            default=None,
            help='Project path for project-scoped install',
        )
        install.add_argument(
            '--link',
            action='store_true',
            help='Symlink local plugin sources instead of copying',
        )
        install.add_argument(
            '--force',
            action='store_true',
            help='Replace an existing managed plugin copy',
        )
        install.add_argument(
            '--disabled',
            action='store_true',
            help='Install but keep the plugin disabled',
        )

        list_cmd = subparsers.add_parser(
            'list',
            help='List installed plugins',
        )
        list_cmd.add_argument(
            '--project-path',
            default=None,
            help='Project path for merged plugin listing',
        )
        list_cmd.add_argument(
            '--json',
            action='store_true',
            help='Print machine-readable JSON',
        )

        toggle = subparsers.add_parser(
            'toggle',
            help='Enable or disable an installed plugin',
        )
        toggle.add_argument('plugin_id')
        toggle.add_argument(
            '--enable',
            action='store_true',
            help='Enable the plugin (default action)',
        )
        toggle.add_argument(
            '--disable',
            action='store_true',
            help='Disable the plugin',
        )
        toggle.add_argument(
            '--scope',
            choices=('global', 'project'),
            default='global',
        )
        toggle.add_argument(
            '--project-path',
            default=None,
        )

        uninstall = subparsers.add_parser(
            'uninstall',
            help='Remove a plugin record',
        )
        uninstall.add_argument('plugin_id')
        uninstall.add_argument(
            '--scope',
            choices=('global', 'project'),
            default='global',
        )
        uninstall.add_argument(
            '--purge',
            action='store_true',
            help='Delete managed plugin files',
        )
        uninstall.add_argument(
            '--project-path',
            default=None,
        )

        parser.set_defaults(func=subparser_func)

    def execute(self):
        command = self.args.plugin_command
        if command == 'install':
            self._install()
        elif command == 'list':
            self._list()
        elif command == 'toggle':
            asyncio.run(self._toggle())
        elif command == 'uninstall':
            asyncio.run(self._uninstall())
        else:
            raise SystemExit(f'Unknown plugin command: {command}')

    def _global_root(self) -> Path:
        return Path(os.environ.get('MS_AGENT_HOME', '~/.ms_agent')).expanduser()

    def _project_path(self) -> str:
        return self.args.project_path or os.getcwd()

    def _install(self) -> None:
        global_root = self._global_root()
        manager = PluginConfigManager(global_dir=global_root)
        installer = PluginInstaller(
            config_manager=manager,
            global_root=global_root,
            project_root=self._project_path(),
        )
        try:
            manifest = installer.install(
                self.args.source,
                scope=self.args.scope,
                project_path=self._project_path(),
                link=self.args.link,
                force=self.args.force,
                enabled=False if self.args.disabled else None,
            )
        except UnsupportedPluginSource as exc:
            raise SystemExit(str(exc)) from exc

        print(
            f"Installed plugin '{manifest.plugin_id}' "
            f"({manifest.format.value}) at {manifest.root}")
        print(f"Capabilities: {', '.join(sorted(manifest.capabilities))}")

    def _list(self) -> None:
        global_root = self._global_root()
        runtime = PluginRuntime(global_root=global_root)
        runtime.start_sync(self._project_path(), 'cli')
        plugins = runtime.list_all()
        if self.args.json:
            print(json.dumps({'plugins': plugins}, indent=2))
            return
        if not plugins:
            print('No plugins installed.')
            return
        for item in plugins:
            status = item.get('status', 'unknown')
            enabled = 'enabled' if item.get('enabled') else 'disabled'
            caps = ', '.join(item.get('capabilities') or [])
            print(
                f"- {item['plugin_id']} [{status}, {enabled}] "
                f"caps={caps or 'none'}"
            )

    async def _toggle(self) -> None:
        if self.args.disable and self.args.enable:
            raise SystemExit('Use only one of --enable or --disable')
        enabled = not self.args.disable
        runtime = PluginRuntime(global_root=self._global_root())
        await runtime.toggle(
            self.args.plugin_id,
            enabled,
            scope=self.args.scope,
            project_path=self._project_path(),
        )
        state = 'enabled' if enabled else 'disabled'
        print(f"Plugin '{self.args.plugin_id}' {state}.")

    async def _uninstall(self) -> None:
        runtime = PluginRuntime(global_root=self._global_root())
        await runtime.uninstall(
            self.args.plugin_id,
            scope=self.args.scope,
            purge=self.args.purge,
        )
        print(f"Plugin '{self.args.plugin_id}' uninstalled.")
