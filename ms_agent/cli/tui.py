# Copyright (c) ModelScope Contributors. All rights reserved.
import argparse

from .base import CLICommand


def subparser_func(args):
    """Factory for the `tui` sub-command."""
    return TuiCMD(args)


def _permission_mode(value: str) -> str:
    from ms_agent.permission.config import normalize_permission_mode

    try:
        return normalize_permission_mode(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _is_local_agent_config(value: str) -> bool:
    """True when --agent points at a file or directory on this machine."""
    from pathlib import Path
    return Path(value).expanduser().exists()


def install_hub_agent(repo: str) -> None:
    """Install an Agent Hub template into the ms-agent workspace.

    Same chain as ``ms-agent agent download -f ms-agent -r <repo>``:
    ``cmd_download`` writes the template's AGENTS.md, mcp.json, skills and
    settings under the global home (``MS_AGENT_HOME`` or ``~/.ms_agent``).
    """
    from modelscope_hub.config import HubConfig

    from ms_agent.agent_hub import cmd_download

    hub = HubConfig()
    code = cmd_download(
        'ms-agent',
        repo,
        endpoint=hub.endpoint,
        token=hub.token,
        username='',
    )
    if code != 0:
        raise SystemExit(code)


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
        agent_config = parser.add_mutually_exclusive_group()
        agent_config.add_argument(
            '--config',
            type=str,
            default=None,
            help='Path to an agent.yaml (or a task dir / modelscope id). '
            'Defaults to the built-in agent.yaml.')
        agent_config.add_argument(
            '--agent',
            type=str,
            default=None,
            help='Install an Agent Hub template and start with it. Copy the '
            'id from https://www.modelscope.cn/agents. '
            'Example: ms-agent --agent ms-agent/stock_data_agent. '
            'A local agent.yaml or task directory is loaded in place.')
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
            type=_permission_mode,
            default='ask',
            help='Permission mode for tool calls: ask (confirm uncertain '
            'calls with you), auto (a model decides them), full-access '
            '(allow them). Default `ask`. Older names restricted, '
            'interactive, strict, delegate are accepted.')
        parser.add_argument(
            '--trust_remote_code',
            action='store_true',
            help='Allow loading external code referenced by the config.')
        parser.add_argument(
            '--mcp-server-file',
            '--mcp_server_file',
            dest='mcp_server_file',
            type=str,
            default=None,
            help='Path to an MCP servers JSON file ({"mcpServers": {...}}) — '
            'stdio / sse / streamable_http servers to connect for this session.'
        )
        parser.add_argument(
            '--emit-events',
            '--emit_events',
            dest='emit_events',
            type=str,
            default=None,
            help='Also append every structured AgentEvent as JSON lines to '
            'this file — the exact wire payloads a WebUI backend would '
            'forward. Use it to inspect/validate the event contract.')
        parser.set_defaults(func=subparser_func)

    def execute(self):
        import importlib.resources as importlib_resources

        config = self.args.config
        explicit_config = bool(config)
        agent = getattr(self.args, 'agent', None)
        if agent:
            if _is_local_agent_config(agent):
                config = agent
                explicit_config = True
            else:
                # Hub id: install AGENTS.md / mcp.json / skills into the
                # workspace, then start on the built-in agent.yaml so those
                # files are what the session uses.
                install_hub_agent(agent)
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
            emit_events=self.args.emit_events,
            mcp_server_file=self.args.mcp_server_file,
            explicit_config=explicit_config,
        )
