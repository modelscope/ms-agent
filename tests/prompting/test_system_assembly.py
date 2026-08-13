# Copyright (c) ModelScope Contributors. All rights reserved.
"""System prompt assembly: layering, the enabled gate, memory segment."""
import asyncio

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.prompting import builtin, workspace_files as wf


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    wf.reset_cache()
    yield tmp_path / 'home'
    wf.reset_cache()


def _agent(tmp_path, **cfg):
    base = {'output_dir': str(tmp_path / 'work')}
    base.update(cfg)
    return LLMAgent(config=OmegaConf.create(base))


def test_disabled_definition_is_byte_stable(home, tmp_path):
    """Golden scenario 5: a self-contained yaml never absorbs workspace files."""
    home.mkdir(parents=True)
    (home / 'SOUL.md').write_text('I am a pirate.\n')
    (home / 'AGENTS.md').write_text('Always speak like a pirate.\n')

    agent = _agent(tmp_path, prompt={'system': 'You are a task pipeline node.'})
    content = agent._build_system_content()
    assert content == 'You are a task pipeline node.'

    agent2 = _agent(tmp_path)  # no prompt.system, still no personalization
    content2 = agent2._build_system_content()
    assert content2 == builtin.BASE_AGENT_PROMPT
    assert 'pirate' not in content2


def test_enabled_definition_layers_in_order(home, tmp_path):
    agent = _agent(tmp_path, personalization={'enabled': True})
    # ensure ran lazily; make the files carry real content
    wf.ensure_home_files()
    (home / 'SOUL.md').write_text('# Soul\nBe direct.\n')
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nAnswer in Chinese.\n')
    work = tmp_path / 'work'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'AGENTS.md').write_text('This project uses TypeScript.\n')
    wf.reset_cache()

    content = agent._build_system_content()
    assert content.startswith(builtin.BASE_AGENT_PROMPT)
    for fragment in ('# Soul', '## Custom Instructions', 'Answer in Chinese.',
                     '## Project Instructions', 'This project uses TypeScript.'):
        assert fragment in content, fragment
    # order: BASE < SOUL < custom < project
    assert (content.index('# Soul') < content.index('## Custom Instructions')
            < content.index('## Project Instructions'))
    # source labels present
    assert 'source="~/.ms_agent/AGENTS.md"' in content
    assert 'source="AGENTS.md"' in content


def test_explicit_system_replaces_base_but_keeps_environment(home, tmp_path):
    wf.ensure_home_files()
    (home / 'SOUL.md').write_text('Custom soul body.\n')
    wf.reset_cache()
    agent = _agent(
        tmp_path,
        prompt={'system': 'You are a custom assistant.'},
        personalization={'enabled': True})
    content = agent._build_system_content()
    assert content.startswith('You are a custom assistant.')
    assert builtin.BASE_AGENT_PROMPT not in content
    assert 'Custom soul body.' in content


def test_legacy_fields_fall_back_until_files_have_content(home, tmp_path):
    """Golden scenario 2: pristine templates must not kill legacy fields."""
    agent = _agent(
        tmp_path,
        personalization={
            'enabled': True,
            'global_instruction': 'Be terse.',
            'project_instruction': 'Use uv.',
        })
    content = agent._build_system_content()
    assert 'Be terse.' in content and 'legacy:settings.json' in content
    assert 'Use uv.' in content and 'legacy:project.instruction' in content

    # user writes the file -> file wins, field silently ignored
    with open(home / 'AGENTS.md', 'a', encoding='utf-8') as f:
        f.write('\nFrom the file.\n')
    wf.reset_cache()
    content = agent._build_system_content()
    assert 'From the file.' in content
    assert 'Be terse.' not in content


def test_memory_guidance_is_a_segment_not_a_config_mutation(home, tmp_path):
    """Golden scenario 7: guidance appears, config.prompt stays untouched."""

    class FakeOrchestrator:
        def get_tool_schemas(self):
            return [{'tool_name': 'memory', 'description': '', 'parameters': {}}]

        def set_llm(self, llm):
            pass

        def init_update_queue(self):
            pass

    agent = _agent(tmp_path)
    before = OmegaConf.to_container(agent.config, resolve=True)
    asyncio.run(agent._register_memory_tool(FakeOrchestrator()))
    after = OmegaConf.to_container(agent.config, resolve=True)
    assert before.get('prompt') == after.get('prompt')  # no mutation
    content = agent._build_system_content()
    assert '## Long-term Memory' in content
    # tool-less backend: no guidance
    agent2 = _agent(tmp_path)

    class ToolLess(FakeOrchestrator):
        def get_tool_schemas(self):
            return []

    asyncio.run(agent2._register_memory_tool(ToolLess()))
    assert agent2._memory_guidance == ''
    assert '## Long-term Memory' not in agent2._build_system_content()


def test_memory_guidance_has_no_hardcoded_tool_names():
    """Backend tool names are dynamic; guidance wording must stay generic."""
    for name in ('memory_read', '`memory`', 'skills_list'):
        assert name not in builtin.MEMORY_TOOL_GUIDANCE
