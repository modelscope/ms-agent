# Copyright (c) ModelScope Contributors. All rights reserved.
"""TUI application: a route-B REPL over the LLMAgent lifecycle with sessions.

Positioning: single user · multi-project · many sessions per project. Every
launch starts a fresh, independent conversation; ``/resume`` restores a past
one; ``/new`` starts another; ``/sessions`` lists them. Sessions are owned by
the M1 ``SessionManager`` (global ``~/.ms_agent/projects/<id>/sessions``) — the
same layer the WebUI will use — so the agent's own per-run session log is
disabled here and the TUI persists the one canonical conversation itself.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from omegaconf import OmegaConf
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Message
from ms_agent.tui.io import RichConsoleIO
from ms_agent.utils.logger import get_logger

logger = get_logger()

_MSG_KEYS = ('role', 'content', 'tool_calls', 'tool_call_id', 'name')


def _args_complete(args: Any) -> bool:
    if isinstance(args, dict):
        return bool(args)
    if isinstance(args, str) and args.strip():
        try:
            json.loads(args)
            return True
        except Exception:
            return False
    return False


def _looks_texty(s: str) -> bool:
    t = s.lstrip()
    return not (t.startswith('{') or t.startswith('['))


def _dict_to_msg(d: dict) -> Message:
    return Message(**{k: d[k] for k in _MSG_KEYS if k in d})


class TuiApp:

    def __init__(
        self,
        config_path: str,
        env_file: Optional[str] = None,
        permission_mode: Optional[str] = None,
        trust_remote_code: bool = False,
        work_dir: Optional[str] = None,
    ) -> None:
        Env.load_dotenv_into_environ(env_file)
        self.console = Console()
        self.trust_remote_code = trust_remote_code
        self.work_dir = str(Path(work_dir).expanduser().resolve()
                            if work_dir else Path.cwd().resolve())

        config = Config.from_task(config_path)
        config = self._prepare_config(config, permission_mode, self.work_dir)
        self.config = config

        from ms_agent.command import CommandRouter, register_builtin_commands
        from ms_agent.command.types import (CommandDef, CommandResult,
                                            CommandResultType)
        self.router = CommandRouter()
        register_builtin_commands(self.router)

        # Session commands are intercepted in _dispatch (they need the
        # SessionManager + REPL control); register defs so /help lists them and
        # is_command() recognizes them.
        async def _noop(ctx):
            return CommandResult(type=CommandResultType.MESSAGE, content='')
        self.router.register(
            CommandDef(name='sessions', description='List sessions in this project',
                       category='session'), _noop)
        self.router.register(
            CommandDef(name='resume',
                       description='Resume a session: /resume <#|id>',
                       category='session'), _noop)

        self.io = RichConsoleIO(console=self.console, router=self.router)

        from ms_agent.agent.llm_agent import LLMAgent
        self.agent = LLMAgent(
            config, trust_remote_code=trust_remote_code, console_io=self.io)

        mode = str(getattr(getattr(config, 'permission', None), 'mode', 'auto'))
        if mode in ('restricted', 'interactive'):
            from ms_agent.tui.permission import TUIPermissionHandler
            self.agent.set_permission_handler(
                TUIPermissionHandler(console=self.console, io=self.io))
        self.permission_mode = mode

        # Session lifecycle (M1). The work dir *is* the project (CC-aligned):
        # sessions live at ~/.ms_agent/projects/<work-dir-key>/sessions, so
        # different work dirs are different projects, each with its own sessions.
        from ms_agent.project import SessionManager
        from ms_agent.project.paths import project_key
        from ms_agent.project.types import Project
        proj = Project(id=project_key(self.work_dir),
                       name=Path(self.work_dir).name or 'project',
                       path=self.work_dir)
        self._sm = SessionManager(proj)
        self._model = str(getattr(getattr(config, 'llm', None), 'model', '') or '')
        self.session = None
        self._log = None
        self._logged = 0  # non-system messages already persisted
        self.messages: List[Message] = [Message(role='system', content='')]

    # -- config shaping --

    @staticmethod
    def _prepare_config(config, permission_mode, work_dir):
        OmegaConf.update(config, 'generation_config.stream', True, merge=True)
        OmegaConf.update(
            config, 'generation_config.stream_output', True, merge=True)
        OmegaConf.update(
            config, 'generation_config.show_reasoning', False, merge=True)
        OmegaConf.update(config, 'output_dir', work_dir, merge=True)
        # The TUI owns session persistence via SessionManager; disable the
        # agent's own per-run session log so turns don't fragment into files.
        OmegaConf.update(config, 'session_log.enabled', False, merge=True)
        if permission_mode:
            OmegaConf.update(
                config, 'permission.mode', permission_mode, merge=True)
        # Merge the work-dir project patch (e.g. a persisted /model override)
        # so it round-trips from <work_dir>/.ms_agent/config.yaml — consistent
        # with where internals live. from_task only reads the config-file dir,
        # which differs when --config points outside the work dir.
        try:
            from ms_agent.config.resolver import ConfigResolver
            patch = ConfigResolver()._load_project_patch(work_dir)
            if patch is not None:
                config = OmegaConf.merge(config, patch)
        except Exception:
            logger.debug('work-dir config patch merge skipped', exc_info=True)
        return config

    # -- session lifecycle --

    def _new_session(self) -> None:
        self.session = self._sm.create(model=self._model or None)
        self._log = self._sm.get_session_log(self.session)
        self._logged = 0
        self.messages = [Message(role='system', content='')]

    def _resume_session(self, session) -> bool:
        self.session = session
        self._log = self._sm.get_session_log(session)
        try:
            dicts = self._log.get_all_messages()
        except Exception:
            dicts = []
        convo = [_dict_to_msg(d) for d in dicts
                 if d.get('role') and d.get('role') != 'system']
        self.messages = [Message(role='system', content='')] + convo
        self._logged = len(convo)
        return True

    def _persist_turn(self) -> None:
        convo = self.messages[1:]
        for m in convo[self._logged:]:
            try:
                self._log.append({k: v for k, v in {
                    'role': m.role,
                    'content': m.content or '',
                    'tool_calls': getattr(m, 'tool_calls', None),
                    'tool_call_id': getattr(m, 'tool_call_id', None),
                    'name': getattr(m, 'name', None),
                }.items() if v not in (None, '')})
            except Exception:
                pass
        self._logged = len(convo)
        # Name the session after its first user turn.
        name = self.session.name
        if name.startswith('Session '):
            first_user = next((m.content for m in convo
                               if m.role == 'user' and m.content), '')
            if first_user:
                name = first_user.strip().splitlines()[0][:40]
        try:
            self._sm.update(self.session.id, name=name,
                            updated_at=datetime.now(timezone.utc).isoformat())
            self.session = self._sm.get(self.session.id) or self.session
        except Exception:
            pass

    # -- rendering --

    def _banner(self) -> None:
        llm = getattr(self.config, 'llm', None)
        tools = list(self.config.tools.keys()) if getattr(
            self.config, 'tools', None) else []
        t = Table.grid(padding=(0, 2))
        t.add_column(style='bold cyan', justify='right')
        t.add_column()
        t.add_row('model', f'{getattr(llm, "service", "?")} / '
                  f'{getattr(llm, "model", "?")}')
        t.add_row('tools', ', '.join(tools) or '[dim](none)[/]')
        t.add_row('perm', self.permission_mode)
        t.add_row('work dir', self.work_dir)
        t.add_row('files', '[dim]internals → .ms_agent/ · '
                  'sessions → ~/.ms_agent/projects/[/]')
        self.console.print(
            Panel(t, title='[bold]ms-agent tui[/]', border_style='cyan',
                  subtitle='[dim]/help /sessions /resume /new /quit[/]'))

    def _render_tool_call(self, tc: dict) -> None:
        name = tc.get('tool_name', '?')
        args = tc.get('arguments', '')
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                pass
        arg_str = json.dumps(args, ensure_ascii=False, indent=2)
        if len(arg_str) > 800:
            arg_str = arg_str[:800] + '\n…'
        self.io.print(Panel(
            Syntax(arg_str, 'json', theme='ansi_dark', word_wrap=True),
            title=f'🔧 {name}', border_style='yellow', expand=False))

    def _render_tool_result(self, msg: Message) -> None:
        content = msg.content if isinstance(msg.content, str) else str(
            msg.content)
        if len(content) > 1200:
            content = content[:1200] + '\n… (truncated)'
        renderable = (Markdown(content)
                      if content.strip() and _looks_texty(content)
                      else content)
        self.io.print(Panel(renderable, title=f'← {msg.name or "result"}',
                            border_style='green', expand=False))

    # -- turn execution --

    async def _agent_turn(self, text: str) -> None:
        self.messages.append(Message(role='user', content=text))
        start = len(self.messages)
        rendered_calls: set = set()
        rendered_results: set = set()
        final = None
        try:
            gen = await self.agent.run(self.messages, stream=True)
            async for msgs in gen:
                final = msgs
                for m in msgs[start:]:
                    if m.role == 'assistant' and m.tool_calls:
                        for tc in m.tool_calls:
                            tid = tc.get('id') or json.dumps(
                                tc, sort_keys=True, default=str)
                            if tid not in rendered_calls and _args_complete(
                                    tc.get('arguments')):
                                rendered_calls.add(tid)
                                self._render_tool_call(tc)
                    elif m.role == 'tool':
                        tid = getattr(m, 'tool_call_id', None) or id(m)
                        if tid not in rendered_results:
                            rendered_results.add(tid)
                            self._render_tool_result(m)
        except Exception as e:
            self.io.end_stream()
            self.console.print(Panel(
                f'[bold]{type(e).__name__}[/]: {e}',
                title='[red]turn failed[/]', border_style='red',
                subtitle='[dim]LOG_LEVEL=INFO for details[/]', expand=False))
            logger.warning('TUI turn failed', exc_info=True)
            return
        self.io.end_stream()
        if final is not None:
            self.messages = final
        self._persist_turn()

    # -- session commands (TUI-owned; need SessionManager + REPL control) --

    def _cmd_sessions(self) -> None:
        sessions = self._sm.list()
        if not sessions:
            self.io.print('[dim]no sessions yet[/]')
            return
        t = Table(show_header=True, header_style='bold', box=None, padding=(0, 2))
        for c in ('#', 'name', 'id', 'updated', 'model'):
            t.add_column(c)
        for i, s in enumerate(sessions):
            marker = '➤' if self.session and s.id == self.session.id else str(i)
            t.add_row(marker, s.name, s.id, (s.updated_at or '')[:19],
                      s.model or '')
        self.io.print(Panel(t, title='sessions', border_style='blue',
                            subtitle='[dim]/resume <#|id>[/]', expand=False))

    def _cmd_resume(self, arg: str) -> None:
        arg = arg.strip()
        sessions = self._sm.list()
        target = None
        if arg.isdigit() and int(arg) < len(sessions):
            target = sessions[int(arg)]
        else:
            target = next((s for s in sessions if s.id == arg), None)
        if target is None:
            self.io.print('[red]not found[/] — use /sessions to list, '
                          '/resume <#|id>')
            return
        self._resume_session(target)
        n = len(self.messages) - 1
        self.console.rule(f'[green]resumed[/] {target.name} '
                          f'[dim]({target.id}, {n} msgs)[/]')
        # replay a short tail so the user has context
        for m in self.messages[1:][-4:]:
            who = {'user': '[cyan]you[/]', 'assistant': '[green]assistant[/]',
                   'tool': '[yellow]tool[/]'}.get(m.role, m.role)
            snippet = (m.content or '')[:200].replace('\n', ' ')
            if snippet:
                self.io.print(f'{who} {snippet}')

    # -- dispatch --

    async def _dispatch(self, text: str) -> bool:
        """Returns True to quit the app."""
        cmd, args = self.router.parse_input(text)
        if cmd == 'sessions':
            self._cmd_sessions()
            return False
        if cmd == 'resume':
            self._cmd_resume(args)
            return False
        if cmd in ('new', 'reset'):
            self._new_session()
            self.console.rule('[green]new session[/] '
                              f'[dim]({self.session.id})[/]')
            return False
        from ms_agent.command.types import CommandContext, CommandResultType
        ctx = CommandContext(
            raw_input=text, command_name=cmd, args=args, source='tui',
            runtime=getattr(self.agent, 'runtime', None),
            extra={'router': self.router, 'messages': self.messages,
                   'config': self.config})
        result = await self.router.dispatch(ctx)
        if result is None:
            await self._agent_turn(text)
            return False
        if result.type == CommandResultType.QUIT:
            if result.content:
                self.console.print(f'[dim]{result.content}[/]')
            return True
        if result.type == CommandResultType.SUBMIT_PROMPT:
            await self._agent_turn(result.content)
            return False
        if result.content:
            self.console.print(
                Panel(result.content, border_style='blue', expand=False))
        return False

    @staticmethod
    def _quiet_logs() -> None:
        level = os.environ.get('LOG_LEVEL', 'ERROR').upper()
        os.environ.setdefault('LOG_LEVEL', 'ERROR')
        if level in ('INFO', 'DEBUG', 'WARNING'):
            return
        lg = logging.getLogger('ms_agent')
        lg.setLevel(logging.ERROR)
        for h in lg.handlers:
            h.setLevel(logging.ERROR)

    # -- main loop --

    def run(self) -> None:
        self._quiet_logs()
        self._banner()
        self._new_session()   # fresh, independent conversation each launch
        while True:
            try:
                text = self.io.read_prompt().strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print('\n[dim]bye[/]')
                break
            if not text:
                continue
            try:
                if self.router.is_command(text):
                    should_quit = asyncio.run(self._dispatch(text))
                else:
                    asyncio.run(self._agent_turn(text))
                    should_quit = False
                if should_quit:
                    break
            except KeyboardInterrupt:
                self.console.print('\n[dim](interrupted)[/]')
                continue


def main(
    config_path: str,
    env_file: Optional[str] = None,
    permission_mode: Optional[str] = None,
    trust_remote_code: bool = False,
    work_dir: Optional[str] = None,
) -> None:
    TuiApp(config_path, env_file=env_file, permission_mode=permission_mode,
           trust_remote_code=trust_remote_code, work_dir=work_dir).run()
