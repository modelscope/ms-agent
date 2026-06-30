# Copyright (c) Alibaba, Inc. and its affiliates.
import sys

import pytest
from omegaconf import OmegaConf

from ms_agent.config import Config
from ms_agent.tools.agent_tool import AgentTool


@pytest.fixture(autouse=True)
def _clean_argv(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['ms-agent'])


def test_top_level_registers_delegations_at_depth_1():
    cfg = Config.from_task('general')  # has subagents -> agent_tools
    at = AgentTool(cfg)
    assert at.enabled
    depths = {s.subagent_depth for s in at._specs.values()}
    assert depths == {1}               # children are one level deeper


def test_depth_at_max_disables_delegation():
    cfg = Config.from_task('general')
    cfg = OmegaConf.merge(cfg, OmegaConf.create({'_subagent_depth': 2}))
    at = AgentTool(cfg)
    assert not at.enabled              # sub-agent at max depth cannot delegate
    assert at._specs == {}


def test_depth_one_still_delegates_children_at_two():
    cfg = Config.from_task('general')
    cfg = OmegaConf.merge(cfg, OmegaConf.create({'_subagent_depth': 1}))
    at = AgentTool(cfg)
    assert at.enabled
    depths = {s.subagent_depth for s in at._specs.values()}
    assert depths == {2}              # which is the cap -> grandchildren blocked
