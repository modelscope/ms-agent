# Copyright (c) Alibaba, Inc. and its affiliates.
import sys

import pytest

from ms_agent.config import Config

ALL = ['general', 'plan', 'explore', 'build', 'research']


@pytest.fixture(autouse=True)
def _clean_argv(monkeypatch):
    # Config.from_task() parses sys.argv for `--key value` overrides; under
    # pytest the runner's argv would otherwise trip its assertion.
    monkeypatch.setattr(sys, 'argv', ['ms-agent'])


@pytest.mark.parametrize('name', ALL)
def test_template_loads(name):
    cfg = Config.from_task(name)
    assert cfg.llm.model
    assert hasattr(cfg, 'tools')
    assert cfg.name in ('agent.yaml', 'agent.yml')


@pytest.mark.parametrize('name', ['plan', 'explore'])
def test_readonly_templates_have_no_write_tools(name):
    cfg = Config.from_task(name)
    inc = list(cfg.tools.file_system.include)
    assert 'read_file' in inc
    assert 'write_file' not in inc
    assert 'edit_file' not in inc


def test_general_expands_subagents():
    cfg = Config.from_task('general')
    names = {d.tool_name for d in cfg.tools.agent_tools.definitions}
    assert names == {'explore', 'build', 'research'}


def test_research_mounts_harness():
    cfg = Config.from_task('research')
    cbs = list(cfg.callbacks)
    assert 'round_reminder' in cbs
    assert 'stop_gate' in cbs
