# Copyright (c) ModelScope Contributors. All rights reserved.
import argparse
import asyncio
import os
from importlib import resources as importlib_resources

from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.utils import get_logger, strtobool
from ms_agent.utils.constants import AGENT_CONFIG_FILE, MS_AGENT_ASCII
from omegaconf import OmegaConf

from .base import CLICommand

logger = get_logger()


def subparser_func(args):
    """ Function which will be called for a specific sub parser.
    """
    return RunCMD(args)


def list_builtin_projects():
    try:
        root = importlib_resources.files('ms_agent').joinpath('projects')
        if not root.exists():
            return []
        return sorted([p.name for p in root.iterdir() if p.is_dir()])
    except Exception as e:
        # Fallback: don't let help crash just because a resource is unavailable.
        logger.warning(f'Could not list built-in projects: {e}')
        return []


def project_help_text():
    projects = list_builtin_projects()
    if projects:
        return (
            'Built-in bundled project name under package ms_agent/projects. '
            f'Available: {", ".join(projects)}')
    return 'Built-in bundled project name under package ms_agent/projects.'


class RunCMD(CLICommand):
    name = 'run'

    def __init__(self, args):
        self.args = args

    def load_env_file(self):
        """Load environment variables from .env file in current directory."""
        env_file = os.path.join(os.getcwd(), '.env')
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        # Only set if not already set in environment
                        if key not in os.environ:
                            os.environ[key] = value
                            logger.debug(f'Loaded {key} from .env file')

    @staticmethod
    def define_args(parsers: argparse.ArgumentParser):
        """Define args for run command."""
        projects = list_builtin_projects()

        parser: argparse.ArgumentParser = parsers.add_parser(RunCMD.name)
        parser.add_argument(
            '--env',
            required=False,
            type=str,
            default=None,
            metavar='PATH',
            help=
            'Path to a .env file. If omitted, loads ./.env from the current '
            'working directory when present; missing file is ignored.')
        parser.add_argument(
            '--query',
            required=False,
            type=str,
            help=
            'The query or prompt to send to the LLM. If not set, will enter an interactive mode.'
        )
        parser.add_argument(
            '--config',
            required=False,
            type=str,
            default=None,
            help='The directory or the repo id of the config file')
        parser.add_argument(
            '--project',
            required=False,
            type=str,
            default=None,
            choices=projects,
            help=project_help_text(),
        )
        parser.add_argument(
            '--trust_remote_code',
            required=False,
            type=str,
            default='false',
            help='Trust the code belongs to the config file, default False')
        parser.add_argument(
            '--load_cache',
            required=False,
            type=str,
            default='false',
            help=
            'Load previous step histories from cache, this is useful when a query fails and retry'
        )
        parser.add_argument(
            '--mcp_config',
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
        parser.add_argument(
            '--animation_mode',
            required=False,
            type=str,
            choices=['auto', 'human'],
            default=None,
            help=
            'Animation mode for video_generate project: auto (default) or human.'
        )
        parser.add_argument(
            '--knowledge_search_paths',
            required=False,
            type=str,
            default=None,
            help=
            'Comma-separated list of paths for knowledge search.'
        )
        parser.set_defaults(func=subparser_func)

    def execute(self):
        if getattr(self.args, 'project', None):
            if self.args.config:
                raise ValueError(
                    'Please specify only one of --config or --project')

            project = self.args.project
            project_trav = importlib_resources.files('ms_agent').joinpath(
                'projects', project)

            if not project_trav.exists():
                projects_root = importlib_resources.files('ms_agent').joinpath(
                    'projects')
                available = []
                if projects_root.exists():
                    available = [
                        p.name for p in projects_root.iterdir() if p.is_dir()
                    ]
                raise ValueError(
                    f'Unknown project: {project}. Available: {available}')

            # as_file ensures we get a real filesystem path even if installed as zip
            with importlib_resources.as_file(project_trav) as project_dir:
                self.args.config = str(project_dir)
                return self._execute_with_config()
        return self._execute_with_config()

    def _execute_with_config(self):
        Env.load_dotenv_into_environ(getattr(self.args, 'env', None))
        if not self.args.config:
            current_dir = os.getcwd()
            if os.path.exists(os.path.join(current_dir, AGENT_CONFIG_FILE)):
                self.args.config = os.path.join(current_dir, AGENT_CONFIG_FILE)
            else:
                # Use built-in default agent.yaml from package
                default_config_path = importlib_resources.files(
                    'ms_agent').joinpath('agent', AGENT_CONFIG_FILE)
                with importlib_resources.as_file(
                        default_config_path) as config_file:
                    self.args.config = str(config_file)
        elif not os.path.exists(self.args.config):
            from modelscope import snapshot_download
            self.args.config = snapshot_download(self.args.config)
        self.args.trust_remote_code = strtobool(
            self.args.trust_remote_code)  # noqa
        self.args.load_cache = strtobool(self.args.load_cache)

        # Propagate animation mode via environment variable for downstream code agents
        if getattr(self.args, 'animation_mode', None):
            os.environ['MS_ANIMATION_MODE'] = self.args.animation_mode

        if os.path.isfile(self.args.config):
            config_path = os.path.abspath(self.args.config)
        else:
            config_path = self.args.config
        author_file = os.path.join(config_path, 'author.txt')
        author = ''
        if os.path.exists(author_file):
            with open(author_file, 'r') as f:
                author = f.read()
        blue_color_prefix = '\033[34m'
        blue_color_suffix = '\033[0m'
        print(
            blue_color_prefix + MS_AGENT_ASCII + blue_color_suffix, flush=True)
        line_start = '═════════════════════════Workflow Contributed By════════════════════════════'
        line_end = '════════════════════════════════════════════════════════════════════════════'
        if author:
            print(
                blue_color_prefix + line_start + blue_color_suffix, flush=True)
            print(
                blue_color_prefix + author.strip() + blue_color_suffix,
                flush=True)
            print(blue_color_prefix + line_end + blue_color_suffix, flush=True)

        config = Config.from_task(self.args.config)

        # If knowledge_search_paths is provided, configure tools.localsearch
        if getattr(self.args, 'knowledge_search_paths', None):
            paths = [
                p.strip() for p in self.args.knowledge_search_paths.split(',')
                if p.strip()
            ]
            if paths:
                if not hasattr(config, 'tools') or config.tools is None:
                    config['tools'] = OmegaConf.create({})
                tl = getattr(config.tools, 'localsearch', None)
                if tl is None or not OmegaConf.is_config(tl):
                    localsearch_config = {
                        'paths': paths,
                        'work_path': './.sirchmunk',
                        'mode': 'FAST',
                    }
                    config.tools['localsearch'] = OmegaConf.create(
                        localsearch_config)
                else:
                    existing = OmegaConf.to_container(tl, resolve=True)
                    existing['paths'] = paths
                    config.tools['localsearch'] = OmegaConf.create(existing)

        if Config.is_workflow(config):
            from ms_agent.workflow.loader import WorkflowLoader
            engine = WorkflowLoader.build(
                config_dir_or_id=self.args.config,
                config=config,
                mcp_server_file=self.args.mcp_server_file,
                load_cache=self.args.load_cache,
                trust_remote_code=self.args.trust_remote_code)
        else:
            from ms_agent.agent.loader import AgentLoader
            engine = AgentLoader.build(
                config_dir_or_id=self.args.config,
                config=config,
                mcp_server_file=self.args.mcp_server_file,
                load_cache=self.args.load_cache,
                trust_remote_code=self.args.trust_remote_code)
        asyncio.run(engine.run(self.args.query))
