# Copyright (c) ModelScope Contributors. All rights reserved.
"""TUI application — a route-A driver over the native LLMAgent lifecycle.

The agent owns one continuous ``run_loop`` per session: a single SessionStart,
automatic context compaction, and no per-turn MCP teardown. The TUI is a thin
driver — it injects three seams and then gets out of the way:

* ``event_sink``   → :class:`RichEventSink` renders the structured event stream.
* ``input_source`` → :class:`PromptToolkitInput` supplies awaitable prompts.
* ``permission``   → :class:`TUIPermissionHandler` confirms restricted tools.

Session switching (``/new`` / ``/resume`` / ``/sessions``) happens *between*
lifecycles: the command signals a pending switch and stops the loop; the driver
repoints the agent's session log at the chosen SessionManager session and runs
again. Message persistence and compaction are the agent's job (route A), so the
driver keeps none of the route-B bookkeeping.

Positioning: single user · one project per work dir · many sessions per project.
"""
from __future__ import annotations

import asyncio
import logging
import os
from omegaconf import OmegaConf
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from types import SimpleNamespace
from typing import Optional, Tuple

from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.tui.input import PromptToolkitInput
from ms_agent.tui.renderer import RichEventSink
from ms_agent.tui.state import TuiState
from ms_agent.tui.theme import DEFAULT_THEME
from ms_agent.utils.logger import get_logger

logger = get_logger()

# Same discriminator WebUI session_overrides use. Writing
# tools.todo_list.plan_filename without mcp:false makes ToolManager treat
# todo_list as an MCP server ('url' or 'command' parameter is required).
# Snapshots default off: TUI has no /rollback, and a home-dir work tree
# would git-add the whole $HOME on the first turn.
TUI_RESOLVER_DEFAULTS = {
    'enable_snapshots': False,
    'tools': {
        'todo_list': {
            'enabled': True,
            'mcp': False,
        },
    },
    # Non-empty so LLMAgent.prepare_skills runs and loads bundled skills
    # (update-config, …). An empty ``{}`` is falsy under OmegaConf.
    'skills': {
        'prompt_injection': 'all',
    },
}


class TuiApp:

    def __init__(
        self,
        config_path: str,
        env_file: Optional[str] = None,
        permission_mode: Optional[str] = None,
        trust_remote_code: bool = False,
        work_dir: Optional[str] = None,
        emit_events: Optional[str] = None,
        mcp_server_file: Optional[str] = None,
        explicit_config: bool = False,
    ) -> None:
        Env.load_dotenv_into_environ(env_file)
        self.console = Console()
        self.theme = DEFAULT_THEME
        self.trust_remote_code = trust_remote_code
        self.work_dir = str(
            Path(work_dir).expanduser().resolve() if work_dir else Path.cwd().
            resolve())
        self._project = self._open_project(self.work_dir)

        config = self._load_runtime_config(
            config_path, self.work_dir, explicit_config=explicit_config)
        config = self._prepare_config(
            config, permission_mode, self.work_dir, self._project)
        self.config = config

        mode = str(
            getattr(getattr(config, 'permission', None), 'mode', 'auto'))
        self.permission_mode = mode
        self._model = str(
            getattr(getattr(config, 'llm', None), 'model', '') or '')

        # Shared state: renderer writes token usage, the input bar reads it.
        self.state = TuiState(
            model=self._model, perm=mode, work_dir=self.work_dir)
        self.renderer = RichEventSink(self.console, self.state, self.theme)

        # Optionally tee every event to a JSONL file (the exact WebUI wire
        # payloads) for contract inspection, without changing what's rendered.
        self._jsonl_sink = None
        event_sink = self.renderer
        if emit_events:
            from ms_agent.ui.events import JsonlEventSink, TeeEventSink
            self._jsonl_sink = JsonlEventSink(emit_events)
            event_sink = TeeEventSink(self.renderer, self._jsonl_sink)

        # Same path as WebUI: ProjectManager.open_folder (find-by-path, else
        # path-key). Sessions then live under that project's id.
        from ms_agent.project import SessionManager
        self._sm = SessionManager(self._project)
        self.session = None

        # Bridge managed config files into the runtime (what a WebUI backend
        # also does): MCP servers from ~/.ms_agent + <work_dir>/.ms_agent
        # mcp.json → mcp_config; skill sources/disabled from skills.json →
        # config.skills. Respects enable/disable; --mcp-server-file wins last.
        from ms_agent.project.paths import global_home
        from ms_agent.tui.managed_config import (merge_skills_into_config,
                                                 resolve_mcp_config)
        home = str(global_home())
        config = merge_skills_into_config(config, home, self.work_dir)
        self.config = config
        self._mcp_config = resolve_mcp_config(home, self.work_dir,
                                              mcp_server_file)

        # Build the agent ONCE with the UI seams injected. load_cache is set
        # per session by _apply_session (True only on resume).
        from ms_agent.agent.llm_agent import LLMAgent
        self.agent = LLMAgent(
            config,
            trust_remote_code=trust_remote_code,
            event_sink=event_sink,
            mcp_config=self._mcp_config)

        # Consume the agent's single command router (no duplicate); register the
        # TUI session commands and drive input through it (slash completion).
        self.router = self.agent._get_command_router()
        self._register_session_commands()
        self.input = PromptToolkitInput(
            self.state, self.router, self.theme, console=self.console)
        self.agent._input_source = self.input

        # Always inject the TUI handler — it is only *called* in interactive
        # mode, but injecting it unconditionally lets /permission switch into
        # interactive at runtime and get real confirmations.
        from ms_agent.tui.permission import TUIPermissionHandler
        self.agent.set_permission_handler(
            TUIPermissionHandler(
                console=self.console,
                theme=self.theme,
                # Lets the menu hold the renderer's draws while it owns the
                # terminal (a sibling tool finishing mid-menu must not print
                # into it) — see RichEventSink.hold_output.
                renderer=self.renderer))

        # ('new', None) | ('resume', '<#|id>') | None, set by session commands.
        self._pending_switch: Optional[Tuple[str, Optional[str]]] = None
        # First chat collected while recovering from a missing API key.
        self._queued_query: Optional[str] = None
        # Sessions this TUI process minted. Empty leftovers may be pruned;
        # WebUI (or another TUI) sessions must not.
        self._owned_session_ids: set[str] = set()

    @staticmethod
    def _apply_provider_credentials(config, overwrite: bool = False) -> None:
        """Fill llm keys from settings.json ``providers.<service>``.

        ``overwrite=True`` is for a live ``/model provider`` edit of the
        current service (replace, don't only fill blanks).
        """
        try:
            from ms_agent.config.model_settings import ModelSettingsManager
            from ms_agent.project.paths import global_home
            raw = ModelSettingsManager(global_home())._load_raw()
        except Exception:
            return
        if not isinstance(raw, dict):
            raw = {}

        def _set(field, value, *, force: bool) -> None:
            if value in (None, ''):
                if force:
                    OmegaConf.update(config, field, '', merge=True)
                return
            if force or not OmegaConf.select(config, field, default=None):
                OmegaConf.update(config, field, value, merge=True)

        service = str(OmegaConf.select(config, 'llm.service', default='') or '')
        providers = raw.get('providers') or {}
        entry = providers.get(service) if isinstance(providers.get(service), dict) else {}
        if not entry and service:
            for pid, item in providers.items():
                if str(pid).lower() == service.lower() and isinstance(item, dict):
                    entry = item
                    break
        if not service:
            return
        # Canonicalize MiniMax → minimax so later lookups hit the builtin id.
        from ms_agent.llm.spec import get_registry
        spec = get_registry().get(service)
        if spec is not None and spec.name != service:
            OmegaConf.update(config, 'llm.service', spec.name, merge=True)
            service = spec.name
            if not entry:
                hit = providers.get(spec.name)
                if isinstance(hit, dict):
                    entry = hit

        key_field = f'llm.{service}_api_key'
        url_field = f'llm.{service}_base_url'
        _set(key_field, entry.get('api_key'), force=overwrite)
        _set('llm.api_key', entry.get('api_key'), force=overwrite)
        _set(url_field, entry.get('base_url'), force=overwrite)
        _set('llm.base_url', entry.get('base_url'), force=overwrite)
        proto = entry.get('protocol')
        if proto and (overwrite or not OmegaConf.select(
                config, 'llm.protocol', default=None)):
            OmegaConf.update(config, 'llm.protocol', proto, merge=True)

    @staticmethod
    def _open_project(work_dir: str):
        """Same ProjectManager.open_folder path WebUI uses for a local folder.

        New mounts inherit PersonalizationSettings.memory_enabled (WebUI's
        default for new projects). An already-registered folder keeps its
        stored flags.
        """
        from ms_agent.project import ProjectManager
        from ms_agent.project.paths import global_home
        from ms_agent.personalization.settings import PersonalizationSettings

        mem = False
        backend = None
        try:
            loaded = PersonalizationSettings().load()
            mem = bool(loaded.memory_enabled)
            backend = loaded.memory_backend
        except Exception:
            pass
        return ProjectManager(base_dir=str(global_home())).open_folder(
            work_dir, memory_enabled=mem, memory_backend=backend)

    # -- config shaping --

    @staticmethod
    def _load_runtime_config(config_path: str,
                             work_dir: str,
                             *,
                             explicit_config: bool = False):
        """Same layered merge WebUI uses (ConfigResolver), not Config.from_task
        alone.

        Default TUI (no ``--config``): framework yaml → settings.json → project
        patch, so WebUI's ``default_model`` / ``llm`` is what the first turn
        actually runs. An explicit ``--config`` yaml still wins over settings.
        """
        from ms_agent.config.resolver import ConfigResolver
        from ms_agent.project.paths import global_home

        resolver = ConfigResolver(
            global_dir=str(global_home()),
            project_root=work_dir,
            defaults=TUI_RESOLVER_DEFAULTS,
        )
        agent_config = Config.from_task(config_path) if explicit_config else None
        return resolver.resolve(
            agent_config=agent_config,
            project_path=work_dir,
        )

    @staticmethod
    def _bind_todo_list_session(cfg, sess_dir: str) -> None:
        """Point the builtin plan tool at this session dir.

        ``mcp: false`` must be set whenever plan_filename is written: a
        ``tools.todo_list`` node without that flag is treated as an MCP server.
        """
        plan_json = os.path.join(sess_dir, 'plan.json')
        plan_md = os.path.join(sess_dir, 'plan.md')
        OmegaConf.update(cfg, 'tools.todo_list.mcp', False, merge=True)
        OmegaConf.update(
            cfg, 'tools.todo_list.plan_filename', plan_json, merge=True)
        OmegaConf.update(
            cfg, 'tools.todo_list.plan_md_filename', plan_md, merge=True)

    @staticmethod
    def _prepare_config(config, permission_mode, work_dir, project=None):
        OmegaConf.update(config, 'generation_config.stream', True, merge=True)
        OmegaConf.update(
            config, 'generation_config.stream_output', True, merge=True)
        # Show the model's thinking (rendered as a dim collapsed block). Whether
        # any reasoning is produced still depends on the model / the config's
        # generation_config.extra_body.enable_thinking.
        OmegaConf.update(
            config, 'generation_config.show_reasoning', True, merge=True)
        OmegaConf.update(config, 'output_dir', work_dir, merge=True)
        # Route A: the agent owns the session log (enables auto-compaction);
        # _apply_session points it at the SessionManager session dir.
        OmegaConf.update(config, 'session_log.enabled', True, merge=True)
        # Interactive lifecycle regardless of stdin detection.
        OmegaConf.update(config, 'interactive', True, merge=True)
        # Same as WebUI: data-driven provider layer (credentials + protocol).
        OmegaConf.update(config, 'llm.use_provider_router', True, merge=True)
        # max_chat_round bounds autonomous *steps*; under route A the counter
        # accumulates across interactive turns (and restores on resume), so a
        # small per-task value would cut a long chat short. Raise it high — the
        # user (not a round cap) ends an interactive session.
        OmegaConf.update(config, 'max_chat_round', 1000, merge=True)
        # Seed before _apply_session writes plan paths, so a fresh TUI without
        # a WebUI-seeded settings.json still does not MCP-connect todo_list.
        OmegaConf.update(config, 'tools.todo_list.mcp', False, merge=True)
        if permission_mode:
            OmegaConf.update(
                config, 'permission.mode', permission_mode, merge=True)
        # The agent auto-adds InputCallback for interactive runs; drop any
        # listed one so restarts across session switches never double-register.
        cbs = [
            c for c in list(getattr(config, 'callbacks', []) or [])
            if c != 'input_callback'
        ]
        OmegaConf.update(config, 'callbacks', cbs, merge=False)
        # Merge a work-dir ``.ms_agent/config.yaml`` pin if one exists.
        # ``/model`` no longer writes this file; skipped when resolve() already
        # applied it.
        if not getattr(config, '_project_patch_applied', False):
            try:
                from ms_agent.config.resolver import ConfigResolver
                patch = ConfigResolver()._load_project_patch(work_dir)
                if patch is not None:
                    config = OmegaConf.merge(config, patch)
            except Exception:
                logger.debug(
                    'work-dir config patch merge skipped', exc_info=True)
        TuiApp._apply_provider_credentials(config)
        # Same files WebUI writes: settings.json personalization + project
        # instruction. File-based AGENTS.md / PROFILE.md are read live.
        if project is not None and getattr(project, 'instruction', ''):
            OmegaConf.update(
                config,
                'personalization.project_instruction',
                project.instruction,
                merge=True,
            )
        try:
            from ms_agent.personalization.settings import PersonalizationSettings
            loaded = PersonalizationSettings().load()
            if loaded.global_instruction:
                OmegaConf.update(
                    config,
                    'personalization.global_instruction',
                    loaded.global_instruction,
                    merge=True,
                )
        except Exception:
            logger.debug('personalization settings merge skipped', exc_info=True)
        if project is not None:
            try:
                from ms_agent.personalization.memory_apply import (
                    apply_project_memory)
                apply_project_memory(config, project)
            except Exception:
                logger.debug('project memory apply skipped', exc_info=True)
        return config

    # -- session commands (registered into the agent's router) --

    def _register_session_commands(self) -> None:
        from ms_agent.command.types import (CommandDef, CommandResult,
                                            CommandResultType)

        async def _sessions(ctx):
            self._render_sessions()
            return CommandResult(type=CommandResultType.MESSAGE, content='')

        async def _resume(ctx):
            self._pending_switch = ('resume', (ctx.args or '').strip())
            if ctx.runtime is not None:
                ctx.runtime.should_stop = True
            return CommandResult(type=CommandResultType.QUIT, content='')

        async def _new(ctx):
            self._pending_switch = ('new', None)
            if ctx.runtime is not None:
                ctx.runtime.should_stop = True
            return CommandResult(type=CommandResultType.QUIT, content='')

        async def _permission(ctx):
            arg = (ctx.args or '').strip().lower()
            if arg not in ('auto', 'strict', 'restricted', 'interactive'):
                return CommandResult(
                    type=CommandResultType.MESSAGE,
                    content=(f'permission mode: {self.state.perm}\n'
                             'usage: /permission <auto|restricted|strict>'))
            try:
                mode = self.agent.set_permission_mode(arg)
            except ValueError as e:
                return CommandResult(
                    type=CommandResultType.MESSAGE, content=str(e))
            self.state.perm = mode
            self.permission_mode = mode
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'permission mode → {mode}')

        self.router.register(
            CommandDef(
                name='permission',
                description='Show or switch permission mode',
                category='config',
                aliases=('mode', )), _permission)
        self.router.register(
            CommandDef(
                name='sessions',
                description='List sessions in this project',
                category='session'), _sessions)
        self.router.register(
            CommandDef(
                name='resume',
                description='Resume a session: /resume <#|id>',
                category='session'), _resume)
        self.router.register(
            CommandDef(
                name='new',
                description='Start a new session',
                category='session',
                aliases=('reset', )), _new)

    # -- session lifecycle --

    def _apply_session(self, session, resume: bool = False) -> None:
        """Point the agent's native session log at this SessionManager session
        so the two never diverge (closes the route-B dir split).

        Targets ``self.agent.config`` (not the app's copy): ``read_history``
        reassigns the agent's config object each ``run_loop``, so the app's
        reference goes stale after the first lifecycle. ``_init_session_log``
        reads this value before ``read_history`` runs, so setting it here (just
        before each run) is what takes effect.

        ``load_cache`` is set per session: ``True`` only when resuming (restore
        the SessionLog into context). For a fresh session it MUST be ``False``,
        otherwise the legacy output_dir/tag history (``read_history``) would be
        loaded when the new SessionLog is still empty — replaying the previous
        session's messages. SessionLog is the single source of truth here.
        """
        sess_dir = str(self._sm.sessions_dir / session.id)
        cfg = self.agent.config
        OmegaConf.update(cfg, 'session_log.dir', sess_dir, merge=True)
        OmegaConf.update(
            cfg, 'session_log.session_key', session.session_key, merge=True)
        # Same as WebUI: plan files live beside the session log, not a
        # project-shared workspace plan.json. mcp:false is required so
        # ToolManager does not treat todo_list as an MCP server.
        self._bind_todo_list_session(cfg, sess_dir)
        # prepare_tools() rebuilds TodoListTool from this config each
        # run_loop; do not patch extra_tools here (those instances are
        # discarded).
        self.config = cfg  # keep the app reference in sync for banners/views
        self.session = session
        self.state.session_name = session.name
        self.agent.load_cache = resume

    def _resume_target(self, arg: str):
        sessions = self._sm.list()
        if arg.isdigit() and int(arg) < len(sessions):
            return sessions[int(arg)]
        return next((s for s in sessions if s.id == arg), None)

    def _session_has_history(self, session) -> bool:
        try:
            return any(
                m.get('role') == 'user' and m.get('content')
                for m in self._sm.get_session_log(session).get_all_messages())
        except Exception:
            return True  # on doubt, keep it

    def _prune_if_empty(self, session) -> None:
        # Only drop unused sessions this process created. A resumed WebUI
        # chat with no user-role line must stay.
        owned = getattr(self, '_owned_session_ids', set())
        if session.id not in owned:
            return
        if not self._session_has_history(session):
            try:
                self._sm.delete(session.id)
                owned.discard(session.id)
            except Exception:
                pass

    def _name_session_from_log(self) -> None:
        """Name a session after its first user line (once), read from its log."""
        if self.session is None or not self.session.name.startswith(
                'Session '):
            return
        try:
            for m in self._sm.get_session_log(self.session).get_all_messages():
                if m.get('role') == 'user' and m.get('content'):
                    name = str(m['content']).strip().splitlines()[0][:40]
                    self._sm.update(self.session.id, name=name)
                    self.session = self._sm.get(
                        self.session.id) or self.session
                    self.state.session_name = self.session.name
                    break
        except Exception:
            pass

    # -- rendering (session views the app owns) --

    def _banner(self) -> None:
        from rich.text import Text

        from ms_agent.utils.constants import MS_AGENT_ASCII

        # Left: the CLI's MS-AGENT wordmark (glyph rows only, frame stripped),
        # a blue gradient. Right: the run info — laid out side by side.
        glyphs = [
            ln[1:-1].strip() for ln in MS_AGENT_ASCII.split('\n')
            if '█' in ln or '╚═╝' in ln
        ]
        width = max(len(g) for g in glyphs)
        glyphs = [g.ljust(width)
                  for g in glyphs]  # equal width, clean right edge
        blues = [
            'bright_blue', 'blue', 'dodger_blue2', 'deep_sky_blue1',
            'cornflower_blue', 'blue'
        ]
        logo = Text()
        for i, row in enumerate(glyphs):
            logo.append(
                row + ('\n' if i < len(glyphs) - 1 else ''),
                style=f'bold {blues[i % len(blues)]}')

        llm = getattr(self.config, 'llm', None)
        tools = list(self.config.tools.keys()) if getattr(
            self.config, 'tools', None) else []
        home = os.path.expanduser('~')
        wd = self.work_dir.replace(home, '~') if home else self.work_dir
        if len(wd) > 38:
            wd = '…' + wd[-37:]
        info = Table.grid(padding=(0, 2))
        info.add_column(style='blue', justify='right')
        info.add_column()
        info.add_row(
            'model',
            f'{getattr(llm, "service", "?")}/{getattr(llm, "model", "?")}')
        info.add_row('tools', ', '.join(tools) or '[dim]none[/]')
        info.add_row('perm', f'[yellow]{self.permission_mode}[/]')
        info.add_row('dir', f'[dim]{wd}[/]')
        info_panel = Panel(
            info,
            title='[bold bright_blue]ms-agent tui[/]',
            border_style='blue',
            padding=(0, 2),
            expand=False)

        banner = Table.grid(padding=(0, 4))
        banner.add_column(no_wrap=True, vertical='middle')  # wordmark intact
        banner.add_column(vertical='middle')
        banner.add_row(logo, info_panel)
        self.console.print()
        self.console.print(banner)
        self.console.print(
            '  [dim]/help  /sessions  /resume  /new  /quit[/]\n')

    def _render_sessions(self) -> None:
        sessions = self._sm.list()
        if not sessions:
            self.console.print('[dim]no sessions yet[/]')
            return
        t = Table(
            show_header=True, header_style='bold', box=None, padding=(0, 2))
        for c in ('#', 'name', 'id', 'updated', 'model'):
            t.add_column(c)
        for i, s in enumerate(sessions):
            marker = (f'[{self.theme.session_marker}]➤[/]'
                      if self.session and s.id == self.session.id else str(i))
            t.add_row(marker, s.name, s.id, (s.updated_at or '')[:19], s.model
                      or '')
        self.console.print(
            Panel(
                t,
                title='sessions',
                border_style='blue',
                subtitle='[dim]/resume <#|id>[/]',
                expand=False))

    def _render_history_tail(self, session, n: int = 6) -> None:
        try:
            msgs = self._sm.get_session_log(session).get_all_messages()
        except Exception:
            msgs = []
        convo = [m for m in msgs if m.get('role') != 'system']
        for m in convo[-n:]:
            who = {
                'user': '[cyan]❯[/]',
                'assistant': '[green]●[/]',
                'tool': '[yellow]▸[/]'
            }.get(m.get('role'), str(m.get('role')))
            snippet = str(m.get('content') or '')[:200].replace('\n', ' ')
            if snippet:
                self.console.print(f'{who} {snippet}')

    @staticmethod
    def _quiet_logs() -> None:
        os.environ.setdefault('LOG_LEVEL', 'ERROR')
        if os.environ.get('LOG_LEVEL',
                          'ERROR').upper() in ('INFO', 'DEBUG', 'WARNING'):
            return
        lg = logging.getLogger('ms_agent')
        lg.setLevel(logging.ERROR)
        for h in lg.handlers:
            h.setLevel(logging.ERROR)

    @staticmethod
    def _is_missing_api_key(exc: BaseException) -> bool:
        from ms_agent.llm.credentials import is_missing_api_key_error
        return is_missing_api_key_error(exc)

    @staticmethod
    def _credential_setup_text(exc: BaseException) -> str:
        from ms_agent.llm.credentials import missing_api_key_setup_text
        return missing_api_key_setup_text(exc)

    def _ensure_command_runtime(self) -> None:
        """Let slash commands run after prepare_llm failed (no live LLM yet)."""
        from ms_agent.agent.runtime import Runtime
        cfg = self.agent.config
        llm = getattr(self.agent, 'llm', None)
        if llm is None:
            llm = SimpleNamespace(
                config=cfg,
                model=str(
                    OmegaConf.select(cfg, 'llm.model', default='') or ''),
                _setup_stub=True,
            )
            self.agent.llm = llm
        if getattr(self.agent, 'runtime', None) is None:
            self.agent.runtime = Runtime(llm=llm)
        elif getattr(self.agent.runtime, 'llm', None) is None:
            self.agent.runtime.llm = llm

    async def _setup_until_ready(self) -> Optional[str]:
        """Prompt until credentials work or the user quits. Returns first chat."""
        from ms_agent.command.interactive import InteractiveSession
        from ms_agent.llm import LLM

        self._ensure_command_runtime()
        session = InteractiveSession(
            self.router,
            source='tui',
            input_source=self.input,
            event_sink=self.renderer,
        )
        while True:
            turn = await session.run_turn(
                messages=None, runtime=self.agent.runtime)
            if turn.action == 'quit':
                return None
            try:
                rebuilt = LLM.from_config(self.agent.config)
            except ValueError as exc:
                if self._is_missing_api_key(exc):
                    self.console.print(
                        Panel(
                            self._credential_setup_text(exc),
                            title='[yellow]still no API key[/]',
                            border_style='yellow',
                            expand=False))
                    continue
                raise
            self.agent.llm = rebuilt
            if self.agent.runtime is not None:
                self.agent.runtime.llm = rebuilt
            return turn.text or ''

    # -- main loop (route A: one lifecycle per session) --

    async def _serve(self) -> None:
        self._banner()
        # Do not wipe empty sessions on startup: WebUI may have created a
        # chat the user has not typed into yet. Empty leftovers from *this*
        # TUI process are pruned when leaving the session (below).
        self.session = self._sm.create(model=self._model or None)
        self._owned_session_ids.add(self.session.id)
        resume = False  # a fresh session reads a prompt; a resumed one restores
        self.renderer.rule(f'session {self.session.id}', 'green')
        while True:
            self._pending_switch = None
            self._apply_session(self.session, resume=resume)
            try:
                query = self._queued_query
                self._queued_query = None
                gen = await self.agent.run(query, stream=True)
                async for _ in gen:
                    pass
            except EOFError:
                break  # Ctrl-D at the prompt exits
            except asyncio.CancelledError:
                break  # generator/teardown cancel on /quit — not a crash
            except KeyboardInterrupt:
                # Ctrl-C interrupts the running turn but keeps the REPL alive.
                # Cap the turn with an assistant marker so the resume below
                # doesn't re-run the interrupted user prompt.
                self.renderer.finalize()
                self.console.print('[dim](interrupted — /quit to exit)[/]')
                try:
                    self._sm.get_session_log(self.session).append({
                        'role':
                        'assistant',
                        'content':
                        '(interrupted)'
                    })
                except Exception:
                    pass
                resume = True
                continue
            except Exception as e:  # noqa: BLE001 — surface, don't crash the REPL
                if isinstance(e, RuntimeError) and (
                        'cancel scope' in str(e) or 'athrow()' in str(e)):
                    break
                self.renderer.finalize()
                if self._is_missing_api_key(e):
                    logger.info('TUI waiting for API key: %s', e)
                    self.console.print(
                        Panel(
                            self._credential_setup_text(e),
                            title='[yellow]setup[/]',
                            border_style='yellow',
                            expand=False))
                    queued = await self._setup_until_ready()
                    if queued is None:
                        break
                    self._queued_query = queued
                    resume = False
                    continue
                logger.warning('TUI turn error', exc_info=True)
                # run_loop already emitted ErrorRaised; the renderer drew the
                # panel. Reprinting it and then `break` looked like a crash
                # (two identical errors, then "bye"). Keep the REPL so the
                # user can /model switch or try again. resume=True restores
                # the sealed failed turn instead of resending it.
                self.console.print(
                    '[dim](turn failed — session still open, '
                    '/model to switch, /quit to exit)[/]')
                resume = True
                continue
            self._name_session_from_log()
            # Resolve a resume target against the live list before pruning.
            switch = self._pending_switch
            resume_target = (
                self._resume_target(switch[1] or '')
                if switch and switch[0] == 'resume' else None)
            if not (resume_target and resume_target.id == self.session.id):
                self._prune_if_empty(self.session)
            if switch is None:
                break  # user quit
            kind = switch[0]
            if kind == 'new':
                self.session = self._sm.create(model=self._model or None)
                self._owned_session_ids.add(self.session.id)
                resume = False
                self.renderer.rule(f'new session {self.session.id}', 'green')
            elif kind == 'resume':
                if resume_target is None:
                    self.console.print(
                        '[yellow]session not found[/] — /sessions to list')
                    resume = True  # re-enter (restore) the current session
                else:
                    self.session = resume_target
                    resume = True
                    self.renderer.rule(f'resumed {resume_target.name}',
                                       'green')
                    self._render_history_tail(resume_target)
        self.console.print('[dim]bye[/]')

    def run(self) -> None:
        self._quiet_logs()
        try:
            asyncio.run(self._serve())
        except KeyboardInterrupt:
            self.console.print('\n[dim]bye[/]')
        finally:
            if self._jsonl_sink is not None:
                self._jsonl_sink.close()


def main(
    config_path: str,
    env_file: Optional[str] = None,
    permission_mode: Optional[str] = None,
    trust_remote_code: bool = False,
    work_dir: Optional[str] = None,
    emit_events: Optional[str] = None,
    mcp_server_file: Optional[str] = None,
    explicit_config: bool = False,
) -> None:
    TuiApp(
        config_path,
        env_file=env_file,
        permission_mode=permission_mode,
        trust_remote_code=trust_remote_code,
        work_dir=work_dir,
        emit_events=emit_events,
        mcp_server_file=mcp_server_file,
        explicit_config=explicit_config).run()
