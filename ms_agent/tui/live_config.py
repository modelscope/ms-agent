# Copyright (c) ModelScope Contributors. All rights reserved.
"""Apply ledger changes on the next user message, inside the same agent.

TUI sets :attr:`LLMAgent._on_user_turn` to :func:`apply_live_config`.
WebUI leaves the attribute unset and keeps its own rebuild path.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from omegaconf import OmegaConf

from ms_agent.llm.message_text import prepend_text
from ms_agent.utils import get_logger

logger = get_logger()

_SKILL_NOTICE = (
    '<system-reminder>\n'
    'Skill inventory updated. The list in the system prompt is from '
    'session start; skills_list is current. Do not mention this notice '
    'to the user.\n'
    '</system-reminder>'
)


def _token(payload: Any) -> str:
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _work_dir(agent) -> str | None:
    work = str(OmegaConf.select(agent.config, 'output_dir', default='') or '')
    return work or None


def _install_llm(agent, rebuilt) -> None:
    from ms_agent.command.builtin.config_cmds import _install_rebuilt_llm
    target = agent.llm
    if target is not None and _install_rebuilt_llm(target, rebuilt):
        if agent.runtime is not None:
            agent.runtime.llm = target
        return
    agent.llm = rebuilt
    if agent.runtime is not None:
        agent.runtime.llm = rebuilt


def _drop_live_llm(agent) -> None:
    """Remove the client that was built with a key the config no longer has.

    The agent stays. Slash commands still read ``config`` off the placeholder.
    Memory tools must not keep the old client either.
    """
    from types import SimpleNamespace
    model = str(OmegaConf.select(agent.config, 'llm.model', default='') or '')
    stub = SimpleNamespace(config=agent.config, model=model, _setup_stub=True)
    agent.llm = stub
    runtime = getattr(agent, 'runtime', None)
    if runtime is not None:
        runtime.llm = stub
    for orch in list(getattr(agent, 'memory_tools', None) or []):
        set_llm = getattr(orch, 'set_llm', None)
        if set_llm is None:
            continue
        try:
            set_llm(None)
        except Exception:
            logger.debug('live llm release skipped', exc_info=True)


def _point_memory_at_llm(agent) -> None:
    for orch in list(getattr(agent, 'memory_tools', None) or []):
        set_llm = getattr(orch, 'set_llm', None)
        if set_llm is not None and agent.llm is not None:
            set_llm(agent.llm)


async def _sync_llm(agent) -> None:
    from ms_agent.llm import LLM
    from ms_agent.llm.credentials import client_rejected_missing_key
    from ms_agent.llm.runtime_token import llm_runtime_token
    if agent.llm is None:
        return
    token = llm_runtime_token(agent.config)
    if getattr(agent, '_llm_fp', None) == token:
        return
    # A placeholder with no fingerprint is startup. The setup prompt owns it.
    # A placeholder that already has a fingerprint was installed because the
    # key was cleared; a later edit must be allowed to build a client again.
    if (getattr(agent.llm, '_setup_stub', False)
            and getattr(agent, '_llm_fp', None) is None):
        return
    try:
        rebuilt = LLM.from_config(agent.config)
    except Exception as exc:
        if client_rejected_missing_key(exc):
            _drop_live_llm(agent)
            agent._llm_fp = token
            return
        logger.debug('live llm rebuild skipped', exc_info=True)
        return
    if rebuilt is None:
        return
    _install_llm(agent, rebuilt)
    agent._llm_fp = token
    _point_memory_at_llm(agent)


def _emit_once(agent, key: str, text: str) -> None:
    seen = getattr(agent, '_live_notice_keys', None)
    if seen is None:
        seen = set()
        agent._live_notice_keys = seen
    if key in seen:
        return
    seen.add(key)
    emit = getattr(agent, '_emit_user_notice', None)
    if emit is not None:
        emit(text)
        return
    logger.error(text)


def _note_unreadable_config(agent) -> None:
    """One sentence per broken ledger file or unreadable skill directory."""
    from pathlib import Path

    from ms_agent.project.paths import global_home

    roots = [Path(global_home())]
    work = _work_dir(agent)
    if work:
        roots.append(Path(work) / '.ms_agent')
    names = ('mcp.json', 'skills.json', 'settings.json')
    for root in roots:
        for name in names:
            path = root / name
            if not path.is_file():
                continue
            try:
                json.loads(path.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                _emit_once(
                    agent, f'json:{path}', f'{name} 读不进去。请检查格式。')
            except OSError:
                continue
        skills = root / 'skills'
        if not skills.is_dir():
            continue
        try:
            next(skills.iterdir(), None)
        except OSError:
            _emit_once(
                agent, f'skills:{skills}',
                '技能目录读不了。请检查这个目录的权限。')


def _search_in_sync(tool, block: dict) -> bool:
    engines = block.get('engines')
    if engines and not isinstance(engines, str):
        wanted = [str(item).lower().strip() for item in engines]
    else:
        wanted = [str(block.get('engine') or 'arxiv').lower().strip()]
    live = [
        str(item).lower().strip()
        for item in (getattr(tool, '_engine_types', None) or [])
    ]
    if live != wanted:
        return False
    keys = getattr(tool, '_api_keys', None) or {}
    fields = {
        'tavily': 'tavily_api_key',
        'exa': 'exa_api_key',
        'serpapi': 'serpapi_api_key',
    }
    for engine in wanted:
        field = fields.get(engine)
        if field and field in block:
            if str(block.get(field) or '') != str(keys.get(engine) or ''):
                return False
    return True


def _find_search_tool(agent):
    manager = getattr(agent, 'tool_manager', None)
    if manager is None:
        return None
    for tool in getattr(manager, 'extra_tools', None) or []:
        if getattr(tool, 'SERVER_NAME', None) == 'web_search':
            return tool
    return None


async def _sync_search(agent) -> None:
    from ms_agent.config.search_settings import SearchSettingsManager
    from ms_agent.project.paths import global_home

    block = SearchSettingsManager(global_home()).raw_block()
    token = _token(block)
    if getattr(agent, '_search_fp', None) == token:
        return
    try:
        OmegaConf.update(agent.config, 'tools.web_search', block, merge=True)
    except Exception:
        logger.debug('live search config update failed', exc_info=True)
        return
    tool = _find_search_tool(agent)
    if tool is None or not getattr(tool, '_engines', None):
        agent._search_fp = token
        return
    if getattr(agent, '_search_fp', None) is None and _search_in_sync(tool, block):
        agent._search_fp = token
        return
    reload = getattr(tool, 'reload_from_config', None)
    if reload is None:
        agent._search_fp = token
        return
    try:
        await reload()
    except Exception:
        logger.debug('live search reload failed', exc_info=True)
        return
    agent._search_fp = token


async def _sync_mcp(agent) -> None:
    runtime = getattr(agent, 'mcp_runtime', None)
    if runtime is None:
        return
    from ms_agent.config.mcp_schema import ResolvedMCPConfig
    from ms_agent.project.paths import global_home
    from ms_agent.tui.managed_config import resolve_mcp_config
    raw = resolve_mcp_config(
        str(global_home()),
        _work_dir(agent),
        getattr(agent, 'mcp_server_file', None),
    ) or {}
    servers = dict((raw.get('mcpServers') or {}))
    plugin = getattr(agent, '_plugin_runtime', None)
    loaded = getattr(getattr(plugin, 'load_result', None), 'mcp_servers', None)
    if isinstance(loaded, dict):
        for name, entry in loaded.items():
            servers.setdefault(name, entry)
    token = _token(servers)
    pending = set(getattr(agent, '_mcp_reconnect_names', None) or ())
    # Config is unchanged. Still look at the live processes: a child may
    # have exited, or a startup that began last turn may have finished.
    # Neither of those is said in the chat. /mcp list carries the status.
    if getattr(agent, '_mcp_fp', None) == token and not pending:
        refresh = getattr(runtime, 'refresh_for_turn', None)
        if refresh is not None:
            try:
                await refresh()
            except Exception:
                logger.debug('live mcp refresh failed', exc_info=True)
        return
    try:
        await runtime.apply_config(ResolvedMCPConfig(mcp_servers=servers))
    except Exception:
        logger.debug('live mcp apply failed', exc_info=True)
    if pending:
        agent._mcp_reconnect_names = set()
    agent._mcp_fp = token


def _sync_skills(agent, messages) -> None:
    runtime = getattr(agent, '_skill_runtime', None)
    skills = getattr(agent.config, 'skills', None)
    if runtime is None or not skills:
        return
    from ms_agent.project.paths import global_home
    from ms_agent.tui.managed_config import merge_skills_into_config
    try:
        merge_skills_into_config(agent.config, str(global_home()),
                                 _work_dir(agent))
        changed = runtime.sync_with_config(agent.config.skills)
    except Exception:
        logger.debug('live skill sync failed', exc_info=True)
        return
    if not changed or not bool(getattr(skills, 'update_notice', False)):
        return
    if not messages or getattr(messages[-1], 'role', None) != 'user':
        return
    messages[-1].content = prepend_text(messages[-1].content, _SKILL_NOTICE)


def _unregister_memory(agent) -> None:
    from ms_agent.memory.unified.memory_tool import MemoryTool
    manager = getattr(agent, 'tool_manager', None)
    if manager is not None:
        doomed = [
            tool for tool in manager.extra_tools
            if isinstance(tool, MemoryTool)
        ]
        manager.extra_tools = [
            tool for tool in manager.extra_tools if tool not in doomed
        ]
        index = getattr(manager, '_tool_index', None) or {}
        for key, val in list(index.items()):
            if val and val[0] in doomed:
                index.pop(key, None)
    agent.memory_tools.clear()
    agent._memory_guidance = ''


async def _sync_memory(agent) -> None:
    runtime = getattr(agent, 'runtime', None)
    pending = bool(getattr(runtime, '_memory_pending', False))
    work = _work_dir(agent)
    if not work:
        return
    from ms_agent.personalization.memory_apply import apply_project_memory
    from ms_agent.project import ProjectManager
    from ms_agent.project.paths import global_home
    project = ProjectManager(base_dir=str(global_home())).find_by_path(work)
    if project is None:
        return
    kind = apply_project_memory(agent.config, project)
    want = kind == 'file'
    have = bool(getattr(agent, 'memory_tools', None))
    if want == have:
        if pending and runtime is not None:
            runtime._memory_pending = False
        return
    if have:
        _unregister_memory(agent)
        try:
            from ms_agent.memory.memory_manager import SharedMemoryManager
            from ms_agent.project.paths import memory_dir
            await SharedMemoryManager.close_matching(str(memory_dir(work)))
        except Exception:
            logger.debug('memory store close skipped', exc_info=True)
    if want:
        load = getattr(agent, 'load_memory', None)
        if load is not None:
            await load()
        if pending:
            if not getattr(agent, 'memory_tools', None):
                _emit_once(agent, 'memory-start', '记忆没有启动。请检查记忆目录。')
            if runtime is not None:
                runtime._memory_pending = False


async def apply_live_config(agent, messages=None) -> None:
    """Refresh skills, MCP, the model client, and memory tools.

    ``messages`` is the turn that is about to run. When it ends in a user
    message, a skill change is prefixed there. Pass ``None`` before the
    first ``create_messages`` so the frozen skill section includes edits
    made at the opening prompt.
    """
    try:
        _note_unreadable_config(agent)
        _sync_skills(agent, messages)
        await _sync_mcp(agent)
        await _sync_search(agent)
        await _sync_llm(agent)
        await _sync_memory(agent)
    except Exception:
        logger.debug('live config sync failed', exc_info=True)
