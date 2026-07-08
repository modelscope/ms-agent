# Copyright (c) ModelScope Contributors. All rights reserved.
"""Bridge managed .ms_agent/{mcp,skills}.json config into the agent runtime."""
import json

from omegaconf import OmegaConf

from ms_agent.config import MCPConfigManager
from ms_agent.config.skills_manager import SkillsConfigManager
from ms_agent.tui.managed_config import (merge_skills_into_config,
                                        resolve_mcp_config)


# ── MCP ────────────────────────────────────────────────────────────────────


def test_mcp_enabled_only_and_meta_stripped(tmp_path):
    home = str(tmp_path / 'home')
    mm = MCPConfigManager(global_root=home, project_root=None)
    mm.add('a', {'type': 'streamable_http', 'url': 'http://a'}, scope='global')
    mm.add('b', {'type': 'streamable_http', 'url': 'http://b'}, scope='global')
    mm.set_enabled('b', False, scope='global')
    r = resolve_mcp_config(home, None, None)
    assert set(r['mcpServers']) == {'a'}  # disabled 'b' dropped
    # meta fields (enabled/meta/source) stripped — only the server config left
    assert r['mcpServers']['a'] == {'type': 'streamable_http', 'url': 'http://a'}


def test_mcp_none_when_empty(tmp_path):
    assert resolve_mcp_config(str(tmp_path / 'home'), None, None) is None


def test_mcp_explicit_file_wins(tmp_path):
    home = str(tmp_path / 'home')
    MCPConfigManager(global_root=home, project_root=None).add(
        'a', {'type': 'streamable_http', 'url': 'http://from-json'},
        scope='global')
    ef = tmp_path / 'explicit.json'
    ef.write_text(json.dumps(
        {'mcpServers': {'a': {'type': 'streamable_http', 'url': 'http://EXPLICIT'}}}))
    r = resolve_mcp_config(home, None, str(ef))
    assert r['mcpServers']['a']['url'] == 'http://EXPLICIT'  # explicit wins last


# ── Skill ──────────────────────────────────────────────────────────────────


def test_skills_sources_appended_and_disabled_unioned(tmp_path):
    home = str(tmp_path / 'home')
    sk = SkillsConfigManager(global_dir=home)
    sk.add_source('/abs/managed-skills', scope='global')
    sk.set_skill_enabled('foo', False, scope='global')
    cfg = OmegaConf.create(
        {'skills': {'sources': [{'type': 'local', 'path': '/existing'}]}})
    cfg = merge_skills_into_config(cfg, home, None)
    srcs = OmegaConf.to_container(cfg.skills.sources)
    assert {'type': 'local', 'path': '/existing'} in srcs  # existing preserved
    assert any(str(s.get('path', '')).endswith('managed-skills')
               for s in srcs)  # managed source appended (string→structured)
    assert 'foo' in list(cfg.skills.disabled)  # disabled unioned


def test_skills_noop_when_empty(tmp_path):
    cfg = OmegaConf.create({'llm': {'model': 'x'}})
    out = merge_skills_into_config(cfg, str(tmp_path / 'home'), None)
    assert not getattr(out, 'skills', None)  # nothing added
