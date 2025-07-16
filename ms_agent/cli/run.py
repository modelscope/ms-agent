# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import asyncio
import os

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.config import Config
from ms_agent.utils import strtobool
from ms_agent.workflow.chain_workflow import ChainWorkflow

from modelscope import snapshot_download
from modelscope.cli.base import CLICommand


def subparser_func(args):
    """ Function which will be called for a specific sub parser.
    """
    return RunCMD(args)


class RunCMD(CLICommand):
    name = 'run'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        """ define args for download command.
        """
        parser: argparse.ArgumentParser = parsers.add_parser(RunCMD.name)
        parser.add_argument(
            '--query',
            required=True,
            nargs='+',
            help=
            'The query or prompt to send to the LLM. Multiple words can be provided as a single query string.'
        )
        parser.add_argument(
            '--config',
            required=False,
            type=str,
            default=None,
            help='The directory or the repo id of the config file')
        parser.add_argument(
            '--trust_remote_code',
            required=False,
            type=str,
            default='false',
            help=
            'Trust the code belongs to the config file, set this if you trust the code'
        )
        parser.add_argument(
            '--load_cache',
            required=False,
            type=str,
            default='false',
            help=
            'Load previous step histories from cache, this is useful when a query fails '
            'and retry')
        parser.add_argument(
            '--mcp_server',
            required=False,
            type=str,
            default=None,
            help='The extra mcp server config')
        parser.add_argument(
            '--mcp_server_file',
            required=False,
            type=str,
            default=None,
            help='An extra mcp server file.')
        parser.add_argument(
            '--openai_api_key',
            required=False,
            type=str,
            default=None,
            help='API key for accessing an OpenAI-compatible service.')
        parser.add_argument(
            '--modelscope_api_key',
            required=False,
            type=str,
            default=None,
            help='API key for accessing ModelScope api-inference services.')
        parser.set_defaults(func=subparser_func)

    def execute(self):
        if not self.args.config:
            current_dir = os.getcwd()
            if os.path.exists(os.path.join(current_dir, 'agent.yaml')):
                self.args.config = os.path.join(current_dir, 'agent.yaml')
        elif not os.path.exists(self.args.config):
            self.args.config = snapshot_download(self.args.config)
        self.args.trust_remote_code: bool = strtobool(
            self.args.trust_remote_code)  # noqa
        self.args.load_cache = strtobool(self.args.load_cache)

        config = Config.from_task(self.args.config)

        if Config.is_workflow(config):
            engine = ChainWorkflow(
                config=config,
                trust_remote_code=self.args.trust_remote_code,
                load_cache=self.args.load_cache,
                mcp_server=self.args.mcp_server,
                mcp_server_file=self.args.mcp_server_file,
                task=self.args.query)
        else:
            engine = LLMAgent(
                config=config,
                trust_remote_code=self.args.trust_remote_code,
                mcp_server=self.args.mcp_server,
                mcp_server_file=self.args.mcp_server_file,
                load_cache=self.args.load_cache,
                task=self.args.query)
        query = self.args.query
        asyncio.run(engine.run(' '.join(query)))
