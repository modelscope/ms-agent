# Copyright (c) ModelScope Contributors. All rights reserved.
"""Tests for MCP config merge rules (design doc §5.4)."""
from __future__ import annotations

from pathlib import Path

import pytest
from omegaconf import OmegaConf

from ms_agent.config.mcp_manager import MCPConfigManager
from ms_agent.config.mcp_schema import merge_mcp_layers, normalize_mcp_server_entry
from ms_agent.config.resolver import ConfigResolver


@pytest.fixture
def tmp_roots(tmp_path: Path):
    global_root = tmp_path / 'global'
    project_root = tmp_path / 'project'
    global_root.mkdir()
    project_root.mkdir()
    return global_root, project_root


class TestNormalizeMcpServerEntry:
    def test_strips_agent_yaml_metadata(self):
        entry = {
            'mcp': True,
            'command': 'npx',
            'args': ['-y', 'pkg'],
            'implementation': 'builtin',
            'trust_remote_code': True,
        }
        normalized = normalize_mcp_server_entry(entry, source='agent_yaml')
        assert normalized is not None
        assert normalized['command'] == 'npx'
        assert 'implementation' not in normalized
        assert normalized['source'] == 'agent_yaml'
        assert normalized['enabled'] is True

    def test_mcp_false_excluded(self):
        assert normalize_mcp_server_entry({'mcp': False, 'command': 'x'}) is None


class TestConfigMergeCases:
    def test_case1_global_only(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A'}, scope='global')
        resolver = ConfigResolver(global_root, project_root)
        resolved = resolver.resolve_mcp()
        assert resolved.mcp_servers['fetch']['enabled'] is True
        assert resolved.mcp_servers['fetch']['command'] == 'A'

    def test_case2_project_reenables(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A', 'enabled': False}, scope='global')
        mgr.set_enabled('fetch', True, scope='project')
        resolver = ConfigResolver(global_root, project_root)
        resolved = resolver.resolve_mcp()
        assert resolved.mcp_servers['fetch']['enabled'] is True
        assert resolved.mcp_servers['fetch']['command'] == 'A'

    def test_case3_agent_yaml_overrides_command(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A'}, scope='global')
        agent_cfg = OmegaConf.create({
            'tools': {
                'fetch': {'mcp': True, 'command': 'B'},
            },
        })
        resolver = ConfigResolver(global_root, project_root, agent_config=agent_cfg)
        resolved = resolver.resolve_mcp()
        assert resolved.mcp_servers['fetch']['command'] == 'B'

    def test_case4_project_overrides_command(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A'}, scope='global')
        mgr.add('fetch', {'command': 'C'}, scope='project')
        resolver = ConfigResolver(global_root, project_root)
        resolved = resolver.resolve_mcp()
        assert resolved.mcp_servers['fetch']['command'] == 'C'

    def test_case5_project_remove_masks_global(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A'}, scope='global')
        mgr.remove('fetch', scope='project')
        resolver = ConfigResolver(global_root, project_root)
        resolved = resolver.resolve_mcp()
        assert resolved.mcp_servers['fetch']['enabled'] is False

    def test_case6_session_reenables(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('fetch', {'command': 'A', 'enabled': False}, scope='global')
        resolver = ConfigResolver(global_root, project_root)
        resolved = resolver.resolve_mcp(
            session_override={'fetch': {'enabled': True}})
        assert resolved.mcp_servers['fetch']['enabled'] is True

    def test_case7_mcp_false_not_in_mcp_servers(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('filesystem', {'command': 'A'}, scope='global')
        agent_cfg = OmegaConf.create({
            'tools': {
                'filesystem': {'mcp': False, 'command': 'B'},
            },
        })
        resolver = ConfigResolver(global_root, project_root, agent_config=agent_cfg)
        resolved = resolver.resolve_mcp()
        assert 'filesystem' not in resolved.mcp_servers

    def test_merge_enabled_inheritance(self):
        base = {'command': 'A', 'enabled': False}
        override = {'command': 'B'}
        merged = merge_mcp_layers({'fetch': base}, {'fetch': override})
        assert merged['fetch']['command'] == 'B'
        assert merged['fetch']['enabled'] is False

    def test_resolve_mcp_all_layers_builtin_shadow(self, tmp_roots):
        global_root, project_root = tmp_roots
        mgr = MCPConfigManager(global_root, project_root)
        mgr.add('filesystem', {'command': 'A'}, scope='global')
        agent_cfg = OmegaConf.create({
            'tools': {
                'filesystem': {'mcp': False, 'command': 'B'},
            },
        })
        resolver = ConfigResolver(global_root, project_root, agent_config=agent_cfg)
        merged = resolver.resolve_mcp_all_layers()
        assert 'filesystem' not in merged
