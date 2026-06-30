import argparse
import os

from .base import CLICommand


def _subparser_func(args):
    return ACPProxyCmd(args)


class ACPProxyCmd(CLICommand):
    """``ms-agent acp-proxy`` -- start an ACP proxy that dispatches to
    multiple backend agents."""

    name = 'acp-proxy'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            ACPProxyCmd.name,
            help='Start an ACP proxy that routes to multiple backend agents',
        )
        parser.add_argument(
            '--config',
            required=True,
            type=str,
            help='Path to the proxy config YAML (defines backends)',
        )
        parser.add_argument(
            '--log-file',
            required=False,
            type=str,
            default=None,
            help='Write logs to this file instead of stderr',
        )
        parser.set_defaults(func=_subparser_func)

    def execute(self):
        config_path = self.args.config
        if not os.path.isabs(config_path):
            config_path = os.path.abspath(config_path)

        from ms_agent.acp.proxy import serve_proxy
        serve_proxy(
            config_path=config_path,
            log_file=self.args.log_file,
        )
