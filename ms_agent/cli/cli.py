import argparse
import sys

from ms_agent.cli.a2a_cmd import A2ACmd, A2ARegistryCmd
from ms_agent.cli.acp_cmd import ACPCmd, ACPRegistryCmd
from ms_agent.cli.acp_proxy_cmd import ACPProxyCmd
from ms_agent.cli.agent import AgentCMD
from ms_agent.cli.app import AppCMD
from ms_agent.cli.cron import CronCMD
from ms_agent.cli.plugin import PluginCMD
from ms_agent.cli.run import RunCMD
from ms_agent.cli.tui import TuiCMD
from ms_agent.cli.ui import UICMD


def _with_default_tui(argv):
    """``ms-agent`` with no subcommand is the terminal UI.

    A bare invocation, or one whose first token is an option, is parsed as
    ``ms-agent tui <those options>``. A leading word stays a subcommand, so a
    typo still prints help instead of starting the UI.
    """
    rest = list(argv[1:])
    if not rest or rest[0].startswith('-'):
        return [argv[0], 'tui', *rest]
    return list(argv)


def run_cmd():
    """This is the entrance of the all the cli commands.

    This cmd imports all other sub commands, for example, `run` and `app`.
    """
    parser = argparse.ArgumentParser(
        'ModelScope-agent Command Line tool',
        usage='ms-agent [<command>] [<args>]  (no command starts tui)')

    subparsers = parser.add_subparsers(
        help='ModelScope-agent commands helpers')

    A2ACmd.define_args(subparsers)
    A2ARegistryCmd.define_args(subparsers)
    ACPCmd.define_args(subparsers)
    ACPProxyCmd.define_args(subparsers)
    ACPRegistryCmd.define_args(subparsers)
    RunCMD.define_args(subparsers)
    TuiCMD.define_args(subparsers)
    AppCMD.define_args(subparsers)
    UICMD.define_args(subparsers)
    CronCMD.define_args(subparsers)
    AgentCMD.define_args(subparsers)
    PluginCMD.define_args(subparsers)

    # unknown args will be handled in config.py
    argv = _with_default_tui(sys.argv)
    args, unknown = parser.parse_known_args(argv[1:])

    if not hasattr(args, 'func'):
        parser.print_help()
        exit(1)
    cmd = args.func(args)
    # ``agent`` subcommands take no positional args and never consume the
    # ad-hoc ``--key value`` overrides that Config.parse_args extracts, so a
    # leftover argument is always a user mistake (e.g. a bare path that would
    # silently fall back to the framework default workspace on upload).
    if unknown and isinstance(cmd, AgentCMD):
        # Only a leftover positional argument warrants the --local-dir hint;
        # for a misspelled option keep the plain unrecognized-arguments error.
        if any(not u.startswith('-') for u in unknown):
            parser.error(
                f'unrecognized arguments: {" ".join(unknown)} '
                '(`ms-agent agent` takes no positional arguments; '
                'use --local-dir to specify a local directory)')
        parser.error(f'unrecognized arguments: {" ".join(unknown)}')
    cmd.execute()


if __name__ == '__main__':
    run_cmd()
