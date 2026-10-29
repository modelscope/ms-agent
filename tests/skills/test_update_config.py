"""The bundled update-config skill is not loaded.

TUI still prepares the skill catalog so user and project skills work.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.skill.catalog import BUILTIN_SKILLS_DIR, SkillCatalog
from ms_agent.skill.harness import fill_harness_placeholders
from ms_agent.tui.app import TuiApp


def test_update_config_is_not_bundled():
    assert not (BUILTIN_SKILLS_DIR / 'update-config' / 'SKILL.md').exists()
    catalog = SkillCatalog(config=OmegaConf.create({}))
    catalog.load_from_config(OmegaConf.create({}))
    assert catalog.get_skill('update-config') is None


def test_other_skills_are_not_rewritten():
    body = 'Keep {memory_md} literal in user skills.'
    out = fill_harness_placeholders(body, None, skill_id='some-user-skill')
    assert out == body


def test_tui_defaults_still_prepare_skills(tmp_path, monkeypatch):
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
    assert agent._skill_catalog.get_skill('update-config') is None
    assert 'update-config' not in agent._build_system_content()
