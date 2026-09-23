"""86119007: update-config skill loads on the real TUI / WebUI boot path.

Same order as run_loop: prepare_runtime → prepare_tools → prepare_skills.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.command.skill_bridge import expand_skill
from ms_agent.llm.utils import Message, collect_response
from ms_agent.skill.catalog import BUILTIN_SKILLS_DIR
from ms_agent.tui.app import TuiApp
from ms_agent.tui.managed_config import merge_skills_into_config


def _boot_agent(cfg) -> LLMAgent:
    agent = LLMAgent(config=cfg, tag='e2e-update-config')
    agent.prepare_runtime()

    async def _setup():
        await agent.prepare_tools()
        await agent.prepare_skills()

    asyncio.run(_setup())
    return agent


def _cleanup(agent: LLMAgent) -> None:
    asyncio.run(agent.cleanup_tools())


def _tui_agent(work: Path, home: Path) -> LLMAgent:
    cfg = TuiApp._load_runtime_config(
        'unused.yaml', str(work), explicit_config=False)
    cfg = TuiApp._prepare_config(cfg, None, str(work))
    cfg = merge_skills_into_config(cfg, str(home), str(work))
    return _boot_agent(cfg)


def test_builtin_skill_is_on_disk():
    assert (BUILTIN_SKILLS_DIR / 'update-config' / 'SKILL.md').is_file(), (
        f'bundled skill missing at {BUILTIN_SKILLS_DIR}')


def test_tui_boot_loads_update_config_into_prompt_and_skill_view(
        isolated_home, work_dir):
    """Default TUI session: L1 in system prompt, playbook only on skill_view."""
    agent = _tui_agent(work_dir, isolated_home)
    try:
        assert agent._skill_catalog is not None
        skill = agent._skill_catalog.get_skill('update-config')
        assert skill is not None

        msgs = asyncio.run(agent.create_messages('帮我把长期记忆打开'))
        system = msgs[0].content
        assert 'update-config' in system
        assert 'skill_view' in system
        assert 'streamable_http' not in system
        assert 'memory.unified_memory' not in system

        toolset = next(
            t for t in (agent.tool_manager.extra_tools or [])
            if getattr(t, 'TOOL_SERVER_NAME', None) == 'skills')
        viewed = json.loads(
            toolset._handle_skill_view({'skill_id': 'update-config'}))
        memory_md = str(
            (work_dir.resolve() / '.ms_agent' / 'memory' / 'MEMORY.md'))
        project_mcp = str(work_dir.resolve() / '.ms_agent' / 'mcp.json')
        global_mcp = str(isolated_home / 'mcp.json')
        body = viewed['content']
        assert memory_md in body
        assert project_mcp in body
        assert global_mcp in body
        assert '/memory on' in body
        assert '/mcp add' in body
        assert 'memory.unified_memory' in body
        assert '{memory_md}' not in body
    finally:
        _cleanup(agent)


def test_tui_slash_update_config_expands_playbook(isolated_home, work_dir):
    agent = _tui_agent(work_dir, isolated_home)
    try:
        result = expand_skill(
            agent._skill_catalog, 'update-config', '打开 memory')
        assert result is not None
        assert '/memory on' in result.content
        assert '打开 memory' in result.content
        assert str(isolated_home / 'mcp.json') in result.content
    finally:
        _cleanup(agent)


def test_webui_defaults_also_load_update_config(isolated_home, work_dir):
    """WebUI _apply_webui_defaults already opts into skills; builtin must load."""
    from ms_agent.config.resolver import ConfigResolver

    resolver = ConfigResolver(
        global_dir=str(isolated_home), project_root=str(work_dir))
    cfg = resolver.resolve(agent_config=None, project_path=str(work_dir))
    if OmegaConf.select(cfg, 'skills', default=None) is None:
        OmegaConf.update(cfg, 'skills', {}, merge=True)
    OmegaConf.update(cfg, 'skills.prompt_injection', 'all', merge=True)
    OmegaConf.update(cfg, 'output_dir', str(work_dir), merge=True)
    cfg = merge_skills_into_config(cfg, str(isolated_home), str(work_dir))

    agent = _boot_agent(cfg)
    try:
        assert agent._skill_catalog.get_skill('update-config') is not None
        system = asyncio.run(
            agent.create_messages('add an MCP server'))[0].content
        assert 'update-config' in system
        assert 'skill_view' in system
    finally:
        _cleanup(agent)


def _tool_name(call) -> str:
    if isinstance(call, dict):
        return str(call.get('tool_name') or '')
    return str(getattr(call, 'tool_name', '') or '')


def _tool_args(call) -> dict:
    raw = call.get('arguments') if isinstance(call, dict) else getattr(
        call, 'arguments', {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


@pytest.mark.live
def test_live_model_views_update_config_to_enable_memory(
        isolated_home, work_dir):
    """Real DashScope turn: NL 'open memory' must load the skill, not guess config.yaml."""
    key = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    if not key:
        pytest.skip('DASHSCOPE_API_KEY missing')
    (isolated_home / 'settings.json').write_text(
        json.dumps({
            'default_model': 'dashscope/qwen3.7-plus',
            'llm': {
                'provider': 'dashscope',
                'model': 'qwen3.7-plus',
            },
            'providers': {
                'dashscope': {
                    'api_key': key,
                    'protocol': 'openai',
                },
            },
        }),
        encoding='utf-8')

    cfg = TuiApp._load_runtime_config(
        'unused.yaml', str(work_dir), explicit_config=False)
    cfg = TuiApp._prepare_config(cfg, None, str(work_dir))
    cfg = merge_skills_into_config(cfg, str(isolated_home), str(work_dir))
    OmegaConf.update(cfg, 'generation_config.stream', False, merge=True)
    OmegaConf.update(cfg, 'interactive', False, merge=True)

    agent = _boot_agent(cfg)
    try:
        agent.prepare_llm()
        agent.runtime.llm = agent.llm
        query = (
            '帮我把这个项目的长期记忆打开，以后对话都要记住：代码用 ruff。'
            '按 ms-agent 真正的配置方式做，不要改 config.yaml。'
            '告诉我 MEMORY.md 的绝对路径。')
        messages = asyncio.run(agent.create_messages(query))
        tools = asyncio.run(agent.tool_manager.get_tools())

        viewed = False
        viewed_body = ''
        calls_log = []
        final_text = ''
        for _round in range(4):
            reply = collect_response(
                agent.llm.generate(messages, tools=tools))
            assert reply is not None
            agent.handle_new_response(messages, reply)
            names = [_tool_name(c) for c in (reply.tool_calls or [])]
            calls_log.append(names)
            if not reply.tool_calls:
                final_text = reply.content or ''
                break
            for call in reply.tool_calls:
                args = _tool_args(call)
                if ('skill_view' in _tool_name(call)
                        and args.get('skill_id') == 'update-config'):
                    viewed = True
            before = len(messages)
            asyncio.run(agent.parallel_tool_call(messages))
            if viewed and not viewed_body:
                for msg in messages[before:]:
                    if getattr(msg, 'role', '') == 'tool':
                        viewed_body += msg.content or ''

        print('LIVE_TOOL_ROUNDS', calls_log)
        print('LIVE_VIEWED', viewed)
        print('LIVE_FINAL_HEAD', (final_text or '')[:500])
        assert viewed, (
            f'model never called skill_view(update-config); calls={calls_log} '
            f'final={final_text[:300]!r}')
        memory_md = str(
            (work_dir.resolve() / '.ms_agent' / 'memory' / 'MEMORY.md'))
        assert memory_md in viewed_body
        blob = (final_text + viewed_body).lower()
        assert '/memory on' in blob or 'memory on' in blob
        assert 'unified_memory' not in (final_text or '').lower() or (
            '不要' in (final_text or '') or 'do not' in (final_text or '').lower()
            or 'not' in (final_text or '').lower())
        if final_text:
            assert memory_md in final_text or '.ms_agent/memory/MEMORY.md' in final_text
    finally:
        _cleanup(agent)
