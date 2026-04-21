import argparse
import os

import json
from ms_agent.config.env import Env
from ms_agent.utils import strtobool

from .base import CLICommand


def subparser_func(args):
    return ACPCmd(args)


def registry_subparser_func(args):
    return ACPRegistryCmd(args)


class ACPCmd(CLICommand):
    name = 'acp'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            ACPCmd.name,
            help='Start an ACP (Agent Client Protocol) server over stdio',
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
            '--max_sessions',
            required=False,
            type=int,
            default=8,
            help='Maximum concurrent ACP sessions (default: 8)',
        )
        parser.add_argument(
            '--session_timeout',
            required=False,
            type=int,
            default=3600,
            help='Session inactivity timeout in seconds (default: 3600)',
        )
        parser.add_argument(
            '--log-file',
            required=False,
            type=str,
            default=None,
            help='Write logs to this file instead of stderr',
        )
        parser.add_argument(
            '--serve-http',
            action='store_true',
            default=False,
            help='Start a non-standard HTTP/SSE service API instead of stdio',
        )
        parser.add_argument(
            '--host',
            required=False,
            type=str,
            default='0.0.0.0',
            help='HTTP host to bind (only with --serve-http, default: 0.0.0.0)',
        )
        parser.add_argument(
            '--port',
            required=False,
            type=int,
            default=8080,
            help='HTTP port to bind (only with --serve-http, default: 8080)',
        )
        parser.add_argument(
            '--api-key',
            required=False,
            type=str,
            default=None,
            help=
            'API key for HTTP authentication (or set MS_AGENT_ACP_API_KEY env)',
        )
        parser.set_defaults(func=subparser_func)

    def execute(self):
        Env.load_dotenv_into_environ(getattr(self.args, 'env', None))

        config_path = self.args.config
        if not os.path.isabs(config_path):
            config_path = os.path.abspath(config_path)

        trust_remote_code = strtobool(self.args.trust_remote_code)

        if getattr(self.args, 'serve_http', False):
            self._serve_http(config_path, trust_remote_code)
        else:
            from ms_agent.acp.server import serve
            serve(
                config_path=config_path,
                trust_remote_code=trust_remote_code,
                max_sessions=self.args.max_sessions,
                session_timeout=self.args.session_timeout,
                log_file=self.args.log_file,
            )

    def _serve_http(self, config_path: str, trust_remote_code: bool):
        """Start the non-standard HTTP/SSE internal service API."""
        import uvicorn
        from fastapi import FastAPI

        from ms_agent.acp.http_adapter import configure_http_adapter

        app = FastAPI(
            title='MS-Agent ACP Internal API',
            description=(
                'Non-standard HTTP/SSE service API for ms-agent ACP server. '
                'This is NOT an ACP-standard transport.'),
        )
        acp_router = configure_http_adapter(
            config_path=config_path,
            trust_remote_code=trust_remote_code,
            max_sessions=self.args.max_sessions,
            session_timeout=self.args.session_timeout,
            api_key=self.args.api_key,
        )
        app.include_router(acp_router)

        uvicorn.run(
            app,
            host=self.args.host,
            port=self.args.port,
            log_level='info',
        )


class ACPRegistryCmd(CLICommand):
    """``ms-agent acp-registry`` -- generate an ``agent.json`` manifest."""

    name = 'acp-registry'

    def __init__(self, args):
        self.args = args

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        parser: argparse.ArgumentParser = parsers.add_parser(
            ACPRegistryCmd.name,
            help='Generate an agent.json manifest for ACP Agent Registry',
        )
        parser.add_argument(
            '--config',
            required=False,
            type=str,
            default=None,
            help=
            'Path to agent config YAML (baked into manifest transport args)',
        )
        parser.add_argument(
            '--output',
            required=False,
            type=str,
            default='agent.json',
            help='Output path for the manifest (default: agent.json)',
        )
        parser.add_argument(
            '--title',
            required=False,
            type=str,
            default='MS-Agent',
            help='Agent display title in the manifest',
        )
        parser.set_defaults(func=registry_subparser_func)

    def execute(self):
        from ms_agent.acp.registry import generate_agent_manifest
        manifest = generate_agent_manifest(
            config_path=self.args.config,
            output_path=self.args.output,
            title=self.args.title,
        )
        print(json.dumps(manifest, indent=2))
