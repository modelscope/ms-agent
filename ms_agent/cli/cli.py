import argparse

from ms_agent.cli.a2a_cmd import A2ACmd, A2ARegistryCmd
from ms_agent.cli.acp_cmd import ACPCmd, ACPRegistryCmd
from ms_agent.cli.acp_proxy_cmd import ACPProxyCmd
from ms_agent.cli.app import AppCMD
from ms_agent.cli.run import RunCMD
from ms_agent.cli.ui import UICMD


def run_cmd():
    """This is the entrance of the all the cli commands.

    This cmd imports all other sub commands, for example, `run` and `app`.
    """
    parser = argparse.ArgumentParser(
        'ModelScope-agent Command Line tool',
        usage='ms-agent <command> [<args>]')

    subparsers = parser.add_subparsers(
        help='ModelScope-agent commands helpers')

    A2ACmd.define_args(subparsers)
    A2ARegistryCmd.define_args(subparsers)
    ACPCmd.define_args(subparsers)
    ACPProxyCmd.define_args(subparsers)
    ACPRegistryCmd.define_args(subparsers)
    RunCMD.define_args(subparsers)
    AppCMD.define_args(subparsers)
    UICMD.define_args(subparsers)

    # unknown args will be handled in config.py
    args, _ = parser.parse_known_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        exit(1)
    cmd = args.func(args)
    cmd.execute()


if __name__ == '__main__':
    run_cmd()
