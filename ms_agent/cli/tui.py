# Copyright (c) ModelScope Contributors. All rights reserved.
import argparse

from .base import CLICommand


def subparser_func(args):
    """Factory for the `tui` sub-command."""
    return TuiCMD(args)


class TuiCMD(CLICommand):
    """Terminal UI: a lightweight REPL over the LLMAgent lifecycle.

    Note: `ui` is taken by the (gradio) webui, so this command is `tui`.
    """

    name = 'tui'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(TuiCMD.name)
        parser.add_argument(
            '--config',
            type=str,
            default=None,
            help='Path to an agent.yaml (or a task dir / modelscope id). '
            'Defaults to the built-in agent.yaml.')
        parser.add_argument(
            '--work-dir',
            '--work_dir',
            dest='work_dir',
            type=str,
            default=None,
            help='Working/project directory (== output_dir). Defaults to the '
            'current directory. Framework internals go to <work_dir>/.ms_agent/; '
            'sessions are global under ~/.ms_agent/projects/.')
        parser.add_argument(
            '--env',
            type=str,
            default=None,
            help='Path to a .env file (defaults to ./.env).')
        parser.add_argument(
            '--permission_mode',
            type=str,
            default='restricted',
            choices=['auto', 'strict', 'restricted', 'interactive'],
            help='Permission mode for tool calls. Default `restricted` so '
            'non-whitelisted tools ask for confirmation.')
        parser.add_argument(
            '--trust_remote_code',
            action='store_true',
            help='Allow loading external code referenced by the config.')
        parser.set_defaults(func=subparser_func)

    def execute(self):
        import importlib.resources as importlib_resources

        config = self.args.config
        if not config:
            # Fall back to the packaged default agent.yaml.
            default_config = importlib_resources.files('ms_agent').joinpath(
                'agent', 'agent.yaml')
            with importlib_resources.as_file(default_config) as p:
                config = str(p)

        from ms_agent.tui.app import main
        main(
            config,
            env_file=self.args.env,
            permission_mode=self.args.permission_mode,
            trust_remote_code=self.args.trust_remote_code,
            work_dir=self.args.work_dir,
        )
