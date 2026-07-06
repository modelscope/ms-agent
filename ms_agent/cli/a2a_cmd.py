import argparse
import os

import json
from ms_agent.config.env import Env
from ms_agent.utils import strtobool

from .base import CLICommand


def subparser_func(args):
    return A2ACmd(args)


def registry_subparser_func(args):
    return A2ARegistryCmd(args)


class A2ACmd(CLICommand):
    """``ms-agent a2a`` -- start an A2A HTTP server."""

    name = 'a2a'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            A2ACmd.name,
            help='Start an A2A (Agent-to-Agent) protocol HTTP server',
        )
        parser.add_argument(
            '--config',
            required=True,
            type=str,
            help='Path to the agent config YAML file (e.g. researcher.yaml)',
        )
        parser.add_argument(
            '--env',
            required=False,
            type=str,
            default=None,
            help='Path to a .env file',
        )
        parser.add_argument(
            '--trust_remote_code',
            required=False,
            type=str,
            default='false',
            help='Trust external code files referenced by the config',
        )
        parser.add_argument(
            '--host',
            required=False,
            type=str,
            default='0.0.0.0',
            help='Host to bind the A2A server (default: 0.0.0.0)',
        )
        parser.add_argument(
            '--port',
            required=False,
            type=int,
            default=5000,
            help='Port to bind the A2A server (default: 5000)',
        )
        parser.add_argument(
            '--max-tasks',
            required=False,
            type=int,
            default=8,
            help='Maximum concurrent A2A tasks (default: 8)',
        )
        parser.add_argument(
            '--task-timeout',
            required=False,
            type=int,
            default=3600,
            help='Task inactivity timeout in seconds (default: 3600)',
        )
        parser.add_argument(
            '--log-file',
            required=False,
            type=str,
            default=None,
            help='Write logs to this file instead of stderr',
        )
        parser.set_defaults(func=subparser_func)

    def execute(self):
        Env.load_dotenv_into_environ(getattr(self.args, 'env', None))

        config_path = self.args.config
        if not os.path.isabs(config_path):
            config_path = os.path.abspath(config_path)

        trust_remote_code = strtobool(self.args.trust_remote_code)

        from ms_agent.a2a.executor import (
            MSAgentA2AExecutor,
            configure_a2a_logging,
        )
        from ms_agent.a2a.agent_card import build_agent_card

        configure_a2a_logging(self.args.log_file)

        agent_card = build_agent_card(
            config_path=config_path,
            host=self.args.host,
            port=self.args.port,
        )

        executor = MSAgentA2AExecutor(
            config_path=config_path,
            trust_remote_code=trust_remote_code,
            max_tasks=self.args.max_tasks,
            task_timeout=self.args.task_timeout,
        )

        from a2a.server.apps import A2AStarletteApplication
        from a2a.server.request_handlers import DefaultRequestHandler
        from a2a.server.tasks import InMemoryTaskStore

        request_handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
        )

        app = A2AStarletteApplication(
            agent_card=agent_card,
            http_handler=request_handler,
        )

        import uvicorn
        uvicorn.run(
            app.build(),
            host=self.args.host,
            port=self.args.port,
            log_level='info',
        )


class A2ARegistryCmd(CLICommand):
    """``ms-agent a2a-registry`` -- generate an A2A Agent Card JSON."""

    name = 'a2a-registry'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            A2ARegistryCmd.name,
            help='Generate an A2A Agent Card JSON for agent discovery',
        )
        parser.add_argument(
            '--config',
            required=False,
            type=str,
            default=None,
            help='Path to agent config YAML (used for metadata extraction)',
        )
        parser.add_argument(
            '--output',
            required=False,
            type=str,
            default='agent-card.json',
            help='Output path for the agent card (default: agent-card.json)',
        )
        parser.add_argument(
            '--host',
            required=False,
            type=str,
            default='0.0.0.0',
            help='Host the agent will be served on (default: 0.0.0.0)',
        )
        parser.add_argument(
            '--port',
            required=False,
            type=int,
            default=5000,
            help='Port the agent will be served on (default: 5000)',
        )
        parser.add_argument(
            '--title',
            required=False,
            type=str,
            default='MS-Agent',
            help='Agent display title in the card',
        )
        parser.set_defaults(func=registry_subparser_func)

    def execute(self):
        from ms_agent.a2a.agent_card import generate_agent_card_json
        card = generate_agent_card_json(
            config_path=self.args.config,
            output_path=self.args.output,
            host=self.args.host,
            port=self.args.port,
            title=self.args.title,
        )
        print(json.dumps(card, indent=2))
