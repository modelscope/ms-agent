# Copyright (c) ModelScope Contributors. All rights reserved.
"""``ms-agent agent`` command -- manage agent workspace files.

Migrated from modelscope-hub's ``ms agent`` command. The business logic lives in
:mod:`ms_agent.agent_hub`; the low-level remote transport is provided by
modelscope-hub (:class:`modelscope_hub.agent.AgentApi`).
"""
from __future__ import annotations

import argparse
import sys
from argparse import RawDescriptionHelpFormatter

from .base import CLICommand

# Static fallback framework list for help text, used only when modelscope-hub is
# not importable at parser-build time (so a missing optional dependency never
# breaks the whole ``ms-agent`` CLI). The authoritative list is resolved
# dynamically when available.
_FALLBACK_FRAMEWORKS = 'qoder, qwenpaw, openclaw, hermes, nanobot, openhuman, ms-agent'


def subparser_func(args):
    return AgentCMD(args)


def _framework_list() -> str:
    try:
        from ms_agent.agent_hub import available_frameworks
        return available_frameworks()
    except Exception:
        return _FALLBACK_FRAMEWORKS


class AgentCMD(CLICommand):
    name = 'agent'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        _FW_LIST = _framework_list()
        _epilog = (
            'subcommand arguments:\n'
            '  upload    -f FRAMEWORK -r REPO [-n NAME] [--local-dir DIR] [--dry-run]\n'
            '  download  -f FRAMEWORK -r REPO [-n NAME] [--local-dir DIR] [--target-framework FW] [--dry-run]\n'
            '  watch     -f FRAMEWORK -r REPO [-n NAME] [--local-dir DIR] [--pull]\n'
            '  list      [--owner OWNER] [--page N] [--page-size N]\n'
            '  status    -f FRAMEWORK [--local-dir DIR]\n'
            '  backups   [-f FRAMEWORK] [-n NAME] [--local-dir DIR]\n'
            '  restore   --from-backup TARGET [-f FRAMEWORK] [-n NAME] [--local-dir DIR]\n'
            '  convert   --from-framework FW --target-framework FW [--from-name NAME] [--target-name NAME] [--local-dir DIR] [--out-dir DIR] [--dry-run]\n'
            '  stop      (no arguments)\n'
            '\n'
            'supported frameworks:\n'
            f'  {_FW_LIST}\n'
            '\n'
            'examples:\n'
            '  ms-agent agent upload -f qwenpaw -r user/my-agent\n'
            '  ms-agent agent download -f qwenpaw -r user/my-agent\n'
            '  ms-agent agent watch -f qwenpaw -r user/my-agent --pull\n'
            '  ms-agent agent convert --from-framework qoder --target-framework qwenpaw\n'
            '  ms-agent agent status -f qwenpaw\n'
            '  ms-agent agent list --owner user\n'
            '  ms-agent agent stop\n')
        agent_parser = parsers.add_parser(
            AgentCMD.name,
            help=
            'Manage agent files (upload, download, watch, list, status, restore, backups, convert, stop).',
            description=
            'Manage agent files across local workspace and remote repositories.',
            epilog=_epilog,
            formatter_class=RawDescriptionHelpFormatter,
        )
        agent_sub = agent_parser.add_subparsers(
            dest='agent_action', metavar='ACTION')
        agent_sub.required = True

        # Shared credential options for network subcommands (falls back to
        # ``ms login`` / MODELSCOPE_API_TOKEN when omitted).
        creds = argparse.ArgumentParser(add_help=False)
        creds.add_argument(
            '--token',
            default=None,
            help='API token (default: `ms login` / MODELSCOPE_API_TOKEN).')
        creds.add_argument(
            '--endpoint',
            default=None,
            help='API endpoint (default: MODELSCOPE_ENDPOINT).')

        _fw_help = f'Agent framework ({_FW_LIST})'

        # ---- upload ----
        p_upload = agent_sub.add_parser(
            'upload',
            parents=[creds],
            help='Upload local agent files to remote repository',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Pack and upload local agent workspace files to a remote repository.',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_upload.add_argument(
            '-f', '--framework', required=True, help=_fw_help)
        p_upload.add_argument(
            '-n',
            '--name',
            default=None,
            help=
            'Local agent name; auto-selects if only one exists, errors if multiple'
        )
        p_upload.add_argument(
            '-r',
            '--repo',
            required=True,
            help=
            'Remote repo identifier, supports owner/name format (e.g. user/my-agent)'
        )
        p_upload.add_argument(
            '--local-dir',
            default=None,
            help=
            'Override local workspace root (default: framework standard path)')
        p_upload.add_argument(
            '--visibility',
            choices=['public', 'private'],
            default='public',
            help='Visibility of the remote repo when created (default: public)'
        )
        p_upload.add_argument(
            '--dry-run',
            action='store_true',
            help='List files that would be uploaded, without actually uploading'
        )

        # ---- download ----
        p_download = agent_sub.add_parser(
            'download',
            parents=[creds],
            help='Download agent files from remote repository',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Download remote agent files and write to local workspace.',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_download.add_argument(
            '-f', '--framework', required=True, help=_fw_help)
        p_download.add_argument(
            '-r',
            '--repo',
            required=True,
            help=
            'Remote repo identifier, supports owner/name format (e.g. user/my-agent)'
        )
        p_download.add_argument(
            '-n',
            '--name',
            default=None,
            help='Local agent name to write as (default: "default")')
        p_download.add_argument(
            '--local-dir',
            default=None,
            help=
            'Override local workspace root (default: framework standard path)')
        p_download.add_argument(
            '--target-framework',
            default=None,
            help=f'Convert to a different framework on download ({_FW_LIST})')
        p_download.add_argument(
            '--dry-run',
            action='store_true',
            help='List files that would be written, without actually writing')

        # ---- watch ----
        p_watch = agent_sub.add_parser(
            'watch',
            parents=[creds],
            help='Start background sync for agent files',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Launch a background daemon that watches local changes and pushes to remote.\n'
            'With --pull, also pulls remote changes to local (bidirectional sync).',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_watch.add_argument('-f', '--framework', required=True, help=_fw_help)
        p_watch.add_argument(
            '-n',
            '--name',
            default=None,
            help='Agent name to sync (default: ALL agents in the workspace)')
        p_watch.add_argument(
            '-r',
            '--repo',
            required=True,
            help=
            'Remote repo identifier, supports owner/name format (e.g. user/my-agent)'
        )
        p_watch.add_argument(
            '--local-dir',
            default=None,
            help=
            'Override local workspace root (default: framework standard path)')
        p_watch.add_argument(
            '--pull',
            action='store_true',
            help=
            'Enable bidirectional sync; pull remote changes to local (default: push-only)'
        )

        # ---- list (remote) ----
        p_list = agent_sub.add_parser(
            'list',
            parents=[creds],
            help='List remote agent repositories',
            description=
            'Query and display remote agent repositories with pagination.',
        )
        p_list.add_argument(
            '--owner',
            default=None,
            help='Filter by owner username or organization name')
        p_list.add_argument(
            '--page',
            dest='page_number',
            type=int,
            default=1,
            help='Page number for pagination (default: 1)')
        p_list.add_argument(
            '--page-size',
            dest='page_size',
            type=int,
            default=10,
            help='Number of items per page (default: 10)')

        # ---- status (local) ----
        p_status = agent_sub.add_parser(
            'status',
            help='Show local agent status for a framework',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Display discovered agents, file counts, and file paths for a framework.',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_status.add_argument(
            '-f', '--framework', required=True, help=_fw_help)
        p_status.add_argument(
            '--local-dir',
            default=None,
            help=
            'Override local workspace root (default: framework standard path)')

        # ---- backups ----
        p_backups = agent_sub.add_parser(
            'backups',
            help='List available backups',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'List backup zip files. Backups are named: {framework}_{name}_{date}_{time}.zip',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_backups.add_argument(
            '-f',
            '--framework',
            default=None,
            help='Filter backups by framework name prefix')
        p_backups.add_argument(
            '-n',
            '--name',
            default=None,
            help='Filter backups by agent name (matches _{name}_ in filename)')
        p_backups.add_argument(
            '--local-dir', default=None, help='Override local workspace root')

        # ---- restore ----
        p_restore = agent_sub.add_parser(
            'restore',
            help='Restore agent files from a backup',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Restore workspace from a backup zip. Backs up current state before overwriting.',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_restore.add_argument(
            '--from-backup',
            required=True,
            help=
            "'last' (most recent matching backup) or a specific backup filename"
        )
        p_restore.add_argument(
            '-f',
            '--framework',
            default=None,
            help="Filter backup candidates by framework (used with 'last')")
        p_restore.add_argument(
            '-n',
            '--name',
            default=None,
            help="Filter backup candidates by agent name (used with 'last')")
        p_restore.add_argument(
            '--local-dir',
            default=None,
            help='Override restore target directory')

        # ---- convert (local only, no network) ----
        p_convert = agent_sub.add_parser(
            'convert',
            help='Convert local agent files between frameworks',
            formatter_class=RawDescriptionHelpFormatter,
            description=
            'Convert agent workspace files from one framework format to another.\n'
            'Skips default template files that have no custom content.\n'
            'Automatically backs up existing target files before writing.',
            epilog=f'supported frameworks: {_FW_LIST}',
        )
        p_convert.add_argument(
            '--from-framework',
            required=True,
            help=f'Source framework to read from ({_FW_LIST})')
        p_convert.add_argument(
            '--target-framework',
            required=True,
            help=f'Target framework to write to ({_FW_LIST})')
        p_convert.add_argument(
            '--from-name',
            default=None,
            help='Source agent name to read (default: "default")')
        p_convert.add_argument(
            '--target-name',
            default=None,
            help='Target agent name to write as (default: same as --from-name)'
        )
        p_convert.add_argument(
            '--local-dir',
            default=None,
            help=
            'Source workspace root to read from (default: source framework path)'
        )
        p_convert.add_argument(
            '--out-dir',
            default=None,
            help=
            'Destination directory to write to (default: target framework path)'
        )
        p_convert.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be written without writing')

        # ---- stop ----
        agent_sub.add_parser(
            'stop',
            help='Stop background watch process',
            description=
            'Gracefully stop the background watch daemon (cross-platform: stop-file + SIGTERM).'
        )

        agent_parser.set_defaults(func=subparser_func)

    def execute(self) -> None:
        from ms_agent.agent_hub import (cmd_backups, cmd_convert, cmd_download,
                                        cmd_list, cmd_restore, cmd_status,
                                        cmd_stop, cmd_upload, cmd_watch)

        args = self.args
        action = args.agent_action

        # Credentials come from the subcommand's --token/--endpoint (network
        # subcommands) or None (local subcommands); HubConfig falls back to
        # ``ms login`` credentials / env when args are None.
        token = getattr(args, 'token', None)
        endpoint = getattr(args, 'endpoint', None)

        username = None
        if action in ('upload', 'watch'):
            from modelscope_hub._openapi import OpenAPIClient
            from modelscope_hub.config import HubConfig
            config = HubConfig(endpoint=endpoint, token=token)
            token = config.token
            endpoint = config.endpoint
            if not token:
                print(
                    "Error: not logged in. Run 'ms login' first.",
                    file=sys.stderr)
                raise SystemExit(1)
            try:
                openapi = OpenAPIClient(config=config)
                user_data = openapi.get_current_user()
                if not user_data:
                    print(
                        'Error: failed to resolve current user: empty response from server.',
                        file=sys.stderr)
                    raise SystemExit(1)
                username = user_data.get('username') or user_data.get(
                    'Username') or ''
            except SystemExit:
                raise
            except Exception as e:
                print(
                    f'Error: failed to resolve current user: {e}',
                    file=sys.stderr)
                raise SystemExit(1)
            if not username:
                print(
                    'Error: failed to resolve current user: server returned empty username.',
                    file=sys.stderr)
                raise SystemExit(1)
        elif action in ('download', 'list'):
            from modelscope_hub.config import HubConfig
            config = HubConfig(endpoint=endpoint, token=token)
            token = config.token
            endpoint = config.endpoint
            if token and action == 'download':
                from modelscope_hub._openapi import OpenAPIClient
                try:
                    openapi = OpenAPIClient(config=config)
                    user_data = openapi.get_current_user()
                    username = user_data.get('username') or user_data.get(
                        'Username') or ''
                except Exception:
                    pass

        if action == 'upload':
            rc = cmd_upload(
                framework=args.framework,
                name=args.name,
                local_dir=args.local_dir,
                repo=args.repo,
                dry_run=args.dry_run,
                visibility=args.visibility,
                endpoint=endpoint,
                token=token,
                username=username,
            )
        elif action == 'download':
            rc = cmd_download(
                framework=args.framework,
                repo=args.repo,
                name=args.name,
                target=args.target_framework,
                local_dir=args.local_dir,
                dry_run=args.dry_run,
                endpoint=endpoint,
                token=token,
                username=username,
            )
        elif action == 'convert':
            rc = cmd_convert(
                source_fw=args.from_framework,
                target_fw=args.target_framework,
                from_name=args.from_name,
                target_name=args.target_name,
                local_dir=args.local_dir,
                out_dir=args.out_dir,
                dry_run=args.dry_run,
            )
        elif action == 'watch':
            rc = cmd_watch(
                framework=args.framework,
                name=args.name,
                local_dir=args.local_dir,
                repo=args.repo,
                pull=args.pull,
                endpoint=endpoint,
                token=token,
                username=username,
            )
        elif action == 'stop':
            rc = cmd_stop()
        elif action == 'list':
            rc = cmd_list(
                owner=args.owner,
                page_number=args.page_number,
                page_size=args.page_size,
                endpoint=endpoint,
                token=token,
            )
        elif action == 'status':
            rc = cmd_status(
                framework=args.framework,
                local_dir=args.local_dir,
            )
        elif action == 'backups':
            rc = cmd_backups(
                framework=getattr(args, 'framework', None),
                name=getattr(args, 'name', None),
                local_dir=args.local_dir,
            )
        elif action == 'restore':
            rc = cmd_restore(
                target=args.from_backup,
                framework=getattr(args, 'framework', None),
                name=getattr(args, 'name', None),
                local_dir=args.local_dir,
            )
        else:
            print(f'Unknown agent action: {action}')
            rc = 1

        if rc:
            raise SystemExit(rc)
