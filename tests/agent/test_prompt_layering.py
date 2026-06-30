# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.agent.templates.compose_prompt import compose_system_prompt
from ms_agent.agent.templates.harness.state_inject import StateInjectCallback
from ms_agent.llm.utils import Message


def _run(coro):
    return asyncio.run(coro)


# ---- compose_system_prompt ------------------------------------------------

def test_compose_prepends_general_base():
    cfg = OmegaConf.create({'prompt': {'base': 'general', 'system': 'SPEC'}})
    compose_system_prompt(cfg)
    assert cfg.prompt.system.startswith('You are MS-Agent')
    assert cfg.prompt.system.rstrip().endswith('SPEC')


def test_compose_prepends_worker_base():
    cfg = OmegaConf.create({'prompt': {'base': 'worker', 'system': 'SPEC'}})
    compose_system_prompt(cfg)
    assert 'focused sub-agent in MS-Agent' in cfg.prompt.system
    assert 'SPEC' in cfg.prompt.system


def test_compose_none_is_untouched():
    cfg = OmegaConf.create({'prompt': {'base': 'none', 'system': 'SPEC'}})
    compose_system_prompt(cfg)
    assert cfg.prompt.system == 'SPEC'


def test_compose_missing_base_is_untouched():
    cfg = OmegaConf.create({'prompt': {'system': 'SPEC'}})
    compose_system_prompt(cfg)
    assert cfg.prompt.system == 'SPEC'


def test_compose_unknown_base_is_untouched():
    cfg = OmegaConf.create({'prompt': {'base': 'nope', 'system': 'SPEC'}})
    compose_system_prompt(cfg)
    assert cfg.prompt.system == 'SPEC'


def test_compose_empty_spec_just_base():
    cfg = OmegaConf.create({'prompt': {'base': 'worker', 'system': ''}})
    compose_system_prompt(cfg)
    assert 'focused sub-agent in MS-Agent' in cfg.prompt.system


# ---- StateInjectCallback --------------------------------------------------

def test_state_inject_fills_placeholders():
    cfg = OmegaConf.create({})
    cb = StateInjectCallback(cfg)
    msgs = [
        Message(
            role='system',
            content='date <current_date>; cwd <cwd>; os <os>; spec'),
    ]
    _run(cb.on_task_begin(Runtime(), msgs))
    c = msgs[0].content
    assert '<current_date>' not in c and '<cwd>' not in c and '<os>' not in c
    assert 'spec' in c


def test_state_inject_ignores_non_system_first_message():
    cfg = OmegaConf.create({})
    cb = StateInjectCallback(cfg)
    msgs = [Message(role='user', content='hello <cwd>')]
    _run(cb.on_task_begin(Runtime(), msgs))
    assert msgs[0].content == 'hello <cwd>'  # untouched


def test_state_inject_disabled():
    cfg = OmegaConf.create({'state_inject': {'enabled': False}})
    cb = StateInjectCallback(cfg)
    msgs = [Message(role='system', content='cwd <cwd>')]
    _run(cb.on_task_begin(Runtime(), msgs))
    assert msgs[0].content == 'cwd <cwd>'  # untouched


def test_state_inject_self_registered():
    import ms_agent.agent.templates  # noqa: F401
    from ms_agent.callbacks import callbacks_mapping
    assert 'state_inject' in callbacks_mapping
