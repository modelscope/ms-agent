"""Bundled update-config skill — Claude Code progressive-disclosure analog.

L1: catalog listing (name + description) in the skill section.
L2: skill_view / /update-config expands the playbook with live paths.
The always-on system prompt must not contain the playbook.
"""
from __future__ import annotations

import json

from omegaconf import OmegaConf

from ms_agent.command.skill_bridge import expand_skill
from ms_agent.skill.catalog import BUILTIN_SKILLS_DIR, SkillCatalog
from ms_agent.skill.prompt_injector import SkillPromptInjector
from ms_agent.skill.skill_tools import SkillToolSet


def _catalog():
    catalog = SkillCatalog(config=OmegaConf.create({}))
    catalog.load_from_config(OmegaConf.create({}))
    return catalog


def test_builtin_dir_contains_update_config():
    skill_md = BUILTIN_SKILLS_DIR / 'update-config' / 'SKILL.md'
    assert skill_md.is_file()


def test_catalog_lists_update_config_in_l1_summary():
    catalog = _catalog()
    skill = catalog.get_skill('update-config')
    assert skill is not None
    summary = catalog.get_skills_summary()
    assert 'update-config' in summary
    assert 'MEMORY.md' in skill.description or '/memory' in skill.description
    assert 'mcp.json' in skill.description or '/mcp' in skill.description
    # L1 is discovery-only: live paths stay out of the listing.
    assert '{memory_md}' not in summary
    assert '.ms_agent/memory/MEMORY.md' not in summary


def test_l1_prompt_section_does_not_include_playbook():
    injector = SkillPromptInjector(_catalog())
    section = injector.build_skill_prompt_section()
    assert 'Available Skills' in section
    assert 'update-config' in section
    assert 'skill_view' in section
    # Playbook body stays out of L1 (description may mention /memory as a trigger).
    assert '## Two scopes' not in section
    assert 'memory.unified_memory' not in section
    assert 'streamable_http' not in section


def test_skill_view_fills_live_paths(tmp_path, monkeypatch):
    home = tmp_path / 'ms_home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'proj'
    work.mkdir()
    cfg = OmegaConf.create({'output_dir': str(work)})
    catalog = _catalog()
    toolset = SkillToolSet(cfg, catalog, enable_manage=False)
    data = json.loads(toolset._handle_skill_view({'skill_id': 'update-config'}))

    memory_md = str((work / '.ms_agent' / 'memory' / 'MEMORY.md').resolve())
    project_mcp = str(work / '.ms_agent' / 'mcp.json')
    global_mcp = str(home / 'mcp.json')
    assert memory_md in data['content']
    assert project_mcp in data['content']
    assert global_mcp in data['content']
    assert '{memory_md}' not in data['content']
    assert '{home}' not in data['content']
    assert '/memory on' in data['content']
    assert '/mcp add' in data['content']
    assert 'config.yaml' in data['content']
    assert 'memory.unified_memory' in data['content']
    assert 'Do not' in data['content']


def test_slash_expand_fills_live_paths(tmp_path, monkeypatch):
    home = tmp_path / 'ms_home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    catalog = _catalog()
    result = expand_skill(catalog, 'update-config', 'turn memory on')
    assert result is not None
    assert '/memory on' in result.content
    assert str(home / 'mcp.json') in result.content
    assert 'turn memory on' in result.content
    assert '{memory_md}' not in result.content


def test_other_skills_are_not_rewritten(tmp_path):
    from ms_agent.skill.harness import fill_harness_placeholders
    body = 'Keep {memory_md} literal in user skills.'
    out = fill_harness_placeholders(body, None, skill_id='some-user-skill')
    assert out == body


def test_tui_defaults_enable_prepare_skills(tmp_path, monkeypatch):
    """Default TUI (no --config) must load bundled skills."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.tui.app import TuiApp

    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'work'
    work.mkdir()
    cfg = TuiApp._load_runtime_config(
        'unused.yaml', str(work), explicit_config=False)
    cfg = TuiApp._prepare_config(cfg, None, str(work))
    assert bool(getattr(cfg, 'skills', None))
    assert OmegaConf.select(cfg, 'skills.prompt_injection') == 'all'

    agent = LLMAgent(config=cfg, tag='tui-skills')
    agent.tool_manager = MagicMock()
    agent.tool_manager.index_extra_tool = AsyncMock()
    asyncio.run(agent.prepare_skills())
    assert agent._skill_catalog is not None
    assert agent._skill_catalog.get_skill('update-config') is not None
    content = agent._build_system_content()
    assert 'update-config' in content
    assert 'skill_view' in content
    assert 'streamable_http' not in content
    assert 'memory.unified_memory' not in content
