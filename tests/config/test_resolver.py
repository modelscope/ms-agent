import json
import pytest
from pathlib import Path

from omegaconf import OmegaConf

from ms_agent.config.resolver import (
    ConfigResolver,
    merge_mcp_configs,
    merge_skills_configs,
)


class TestConfigResolver:
    @pytest.fixture
    def global_dir(self, tmp_path):
        d = tmp_path / '.ms_agent'
        d.mkdir()
        return d

    @pytest.fixture
    def resolver(self, global_dir):
        return ConfigResolver(global_dir=str(global_dir))

    def test_resolve_defaults_only(self, resolver):
        config = resolver.resolve()
        assert hasattr(config, 'llm')
        assert hasattr(config, 'tools')

    def test_resolve_with_agent_config_path(self, resolver, tmp_path):
        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text('llm:\n  model: test-model\nmax_chat_round: 5\n')
        config = resolver.resolve(agent_config=str(agent_yaml))
        assert config.llm.model == 'test-model'
        assert config.max_chat_round == 5

    def test_resolve_with_agent_config_dictconfig(self, resolver):
        agent_cfg = OmegaConf.create({'llm': {'model': 'inline-model'}})
        config = resolver.resolve(agent_config=agent_cfg)
        assert config.llm.model == 'inline-model'

    def test_agent_config_overrides_defaults(self, resolver, tmp_path):
        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text(
            'llm:\n  service: openai\n  model: gpt-4\n'
        )
        config = resolver.resolve(agent_config=str(agent_yaml))
        assert config.llm.service == 'openai'
        assert config.llm.model == 'gpt-4'

    def test_global_settings_applied(self, global_dir, tmp_path):
        settings = {
            'llm': {
                'provider': 'openai',
                'model': 'gpt-4.1',
                'api_key': 'sk-test',
                'base_url': 'https://api.openai.com/v1',
            }
        }
        (global_dir / 'settings.json').write_text(json.dumps(settings))
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert config.llm.service == 'openai'
        assert config.llm.model == 'gpt-4.1'

    def test_agent_config_overrides_global(self, global_dir, tmp_path):
        settings = {'llm': {'provider': 'openai', 'model': 'gpt-4'}}
        (global_dir / 'settings.json').write_text(json.dumps(settings))

        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text('llm:\n  model: qwen-custom\n')

        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve(agent_config=str(agent_yaml))
        assert config.llm.model == 'qwen-custom'

    def test_project_patch_overrides_agent(self, resolver, tmp_path):
        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text('llm:\n  model: base-model\nmax_chat_round: 10\n')

        project_path = tmp_path / 'my_project'
        project_path.mkdir()
        ms_agent_dir = project_path / '.ms-agent'
        ms_agent_dir.mkdir()
        (ms_agent_dir / 'config.yaml').write_text(
            'max_chat_round: 50\n'
        )

        config = resolver.resolve(
            agent_config=str(agent_yaml),
            project_path=str(project_path),
        )
        assert config.llm.model == 'base-model'
        assert config.max_chat_round == 50

    def test_session_overrides_on_top(self, resolver, tmp_path):
        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text('llm:\n  model: base\nmax_chat_round: 10\n')

        config = resolver.resolve(
            agent_config=str(agent_yaml),
            session_overrides={'llm': {'model': 'session-model'}},
        )
        assert config.llm.model == 'session-model'
        assert config.max_chat_round == 10

    def test_five_layer_precedence(self, global_dir, tmp_path):
        """Full chain: defaults < global < agent < project < session."""
        settings = {'llm': {'provider': 'dashscope', 'model': 'global-m'}}
        (global_dir / 'settings.json').write_text(json.dumps(settings))

        agent_yaml = tmp_path / 'agent.yaml'
        agent_yaml.write_text('llm:\n  model: agent-m\n')

        project_path = tmp_path / 'proj'
        project_path.mkdir()
        (project_path / '.ms-agent').mkdir()
        (project_path / '.ms-agent' / 'config.yaml').write_text(
            'llm:\n  model: project-m\n'
        )

        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve(
            agent_config=str(agent_yaml),
            project_path=str(project_path),
            session_overrides={'llm': {'model': 'session-m'}},
        )
        assert config.llm.model == 'session-m'

    def test_fill_missing_fields_applied(self, resolver):
        config = resolver.resolve()
        assert hasattr(config, 'tools')
        assert hasattr(config, 'callbacks')

    def test_missing_global_settings_no_error(self, tmp_path):
        resolver = ConfigResolver(global_dir=str(tmp_path / 'nonexistent'))
        config = resolver.resolve()
        assert hasattr(config, 'llm')

    def test_corrupt_global_settings_no_error(self, global_dir):
        (global_dir / 'settings.json').write_text('not json{{{')
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert hasattr(config, 'llm')

    def test_missing_project_patch_no_error(self, resolver, tmp_path):
        config = resolver.resolve(project_path=str(tmp_path / 'no_project'))
        assert hasattr(config, 'llm')


class TestMergeMCP:
    def test_union_by_name(self):
        g = {'mcpServers': {'a': {'cmd': 'x'}, 'b': {'cmd': 'y'}}}
        p = {'mcpServers': {'c': {'cmd': 'z'}}}
        result = merge_mcp_configs(g, p)
        assert set(result['servers'].keys()) == {'a', 'b', 'c'}

    def test_project_overrides_global(self):
        g = {'mcpServers': {'s': {'cmd': 'old', 'env': {'K': '1'}}}}
        p = {'mcpServers': {'s': {'cmd': 'new'}}}
        result = merge_mcp_configs(g, p)
        assert result['servers']['s']['cmd'] == 'new'
        assert result['servers']['s']['_scope'] == 'project'

    def test_enabled_defaults_true(self):
        g = {'mcpServers': {'s': {'cmd': 'x'}}}
        result = merge_mcp_configs(g, {})
        assert result['servers']['s']['enabled'] is True

    def test_preserves_explicit_enabled_false(self):
        g = {'mcpServers': {'s': {'cmd': 'x', 'enabled': False}}}
        result = merge_mcp_configs(g, {})
        assert result['servers']['s']['enabled'] is False

    def test_empty_inputs(self):
        assert merge_mcp_configs({}, {}) == {}

    def test_scope_tag(self):
        g = {'mcpServers': {'a': {'cmd': 'x'}}}
        p = {'mcpServers': {'b': {'cmd': 'y'}}}
        result = merge_mcp_configs(g, p)
        assert result['servers']['a']['_scope'] == 'global'
        assert result['servers']['b']['_scope'] == 'project'

    def test_flat_format(self):
        g = {'a': {'cmd': 'x'}}
        result = merge_mcp_configs(g, {})
        assert 'a' in result['servers']


class TestMergeSkills:
    def test_sources_appended(self):
        g = {'sources': ['/global/s1']}
        p = {'sources': ['/project/s2']}
        result = merge_skills_configs(g, p)
        assert len(result['sources']) == 2

    def test_disabled_union(self):
        g = {'disabled': ['a', 'b']}
        p = {'disabled': ['b', 'c']}
        result = merge_skills_configs(g, p)
        assert set(result['disabled']) == {'a', 'b', 'c'}

    def test_empty_inputs(self):
        result = merge_skills_configs({}, {})
        assert result['sources'] == []
        assert result['disabled'] == []

    def test_enabled_map_project_wins(self):
        g = {'sources': [{'name': 's1', 'enabled': True}]}
        p = {'sources': [{'name': 's1', 'enabled': False}]}
        result = merge_skills_configs(g, p)
        assert result['_enabled_map']['s1'] is False

    def test_no_duplicate_sources(self):
        shared = '/same/path'
        g = {'sources': [shared]}
        p = {'sources': [shared]}
        result = merge_skills_configs(g, p)
        assert result['sources'].count(shared) == 1


class TestMCPInResolver:
    def test_mcp_merged_into_config(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        mcp_data = {'mcpServers': {'my-mcp': {'command': 'node', 'args': ['server.js']}}}
        (global_dir / 'mcp.json').write_text(json.dumps(mcp_data))

        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert hasattr(config, '_merged_mcp')
        assert 'my-mcp' in config._merged_mcp.servers

    def test_skills_merged_into_config(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        skills_data = {'sources': ['/path/to/skills'], 'disabled': ['bad-skill']}
        (global_dir / 'skills.json').write_text(json.dumps(skills_data))

        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert hasattr(config, '_merged_skills')
        assert 'bad-skill' in list(config._merged_skills.disabled)


class TestPersonalizationInResolver:

    def test_personalization_mapped_from_settings(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        settings = {
            'personalization': {
                'global_instruction': 'Be concise and helpful.',
                'memory_enabled': True,
                'memory_backend': 'file_based',
            }
        }
        (global_dir / 'settings.json').write_text(json.dumps(settings))
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert config.personalization.global_instruction == 'Be concise and helpful.'
        assert config.personalization.memory_enabled is True
        assert config.personalization.memory_backend == 'file_based'

    def test_personalization_absent_no_error(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        (global_dir / 'settings.json').write_text(json.dumps({'llm': {'model': 'x'}}))
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert not hasattr(config, 'personalization') or config.personalization is None

    def test_project_instruction_from_project_patch(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        project_path = tmp_path / 'my_project'
        project_path.mkdir()
        ms_agent_dir = project_path / '.ms-agent'
        ms_agent_dir.mkdir()
        (ms_agent_dir / 'config.yaml').write_text(
            'personalization:\n  project_instruction: "Use TypeScript."\n'
        )
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve(project_path=str(project_path))
        assert config.personalization.project_instruction == 'Use TypeScript.'

    def test_empty_instruction_not_mapped(self, tmp_path):
        global_dir = tmp_path / '.ms_agent'
        global_dir.mkdir()
        settings = {'personalization': {'global_instruction': ''}}
        (global_dir / 'settings.json').write_text(json.dumps(settings))
        resolver = ConfigResolver(global_dir=str(global_dir))
        config = resolver.resolve()
        assert not hasattr(config, 'personalization') or config.personalization is None
