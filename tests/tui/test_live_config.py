# Copyright (c) ModelScope Contributors. All rights reserved.
"""Next-message config sync stays on the same agent."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from omegaconf import OmegaConf

from ms_agent.tui.live_config import apply_live_config


@pytest.mark.asyncio
async def test_model_change_rebuilds_the_client_in_place():
    config = OmegaConf.create({
        'llm': {
            'service': 'openai',
            'model': 'gpt-4o',
        },
        'generation_config': {
            'stream': True,
        },
    })
    live = SimpleNamespace(model='old', config=config, _setup_stub=False)
    agent = SimpleNamespace(
        config=config,
        llm=live,
        runtime=SimpleNamespace(llm=live),
        memory_tools=[],
        _skill_runtime=None,
        mcp_runtime=None,
        _llm_fp='stale',
        _mcp_fp=None,
        _memory_guidance='',
    )

    class Rebuilt:
        def __init__(self):
            self.model = 'gpt-4o'
            self.config = config

    with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
        await apply_live_config(agent, None)
    assert agent.llm.model == 'gpt-4o'
    assert agent.runtime.llm.model == 'gpt-4o'
    assert agent._llm_fp != 'stale'


@pytest.mark.asyncio
async def test_unchanged_token_does_not_rebuild():
    from ms_agent.llm.runtime_token import llm_runtime_token
    config = OmegaConf.create({
        'llm': {
            'service': 'openai',
            'model': 'gpt-4o',
        },
    })
    live = SimpleNamespace(model='gpt-4o', config=config, _setup_stub=False)
    agent = SimpleNamespace(
        config=config,
        llm=live,
        runtime=SimpleNamespace(llm=live),
        memory_tools=[],
        _skill_runtime=None,
        mcp_runtime=None,
        _llm_fp=llm_runtime_token(config),
        _mcp_fp=None,
    )
    with patch('ms_agent.llm.LLM.from_config') as rebuild:
        await apply_live_config(agent, None)
    rebuild.assert_not_called()


@pytest.mark.asyncio
async def test_startup_stub_is_left_alone():
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
        },
    })
    live = SimpleNamespace(config=config, model='Qwen/Qwen3.8-Flash-Next',
                           _setup_stub=True)
    agent = SimpleNamespace(
        config=config,
        llm=live,
        runtime=SimpleNamespace(llm=live),
        memory_tools=[],
        _skill_runtime=None,
        mcp_runtime=None,
        _llm_fp=None,
    )
    with patch('ms_agent.llm.LLM.from_config') as rebuild:
        await apply_live_config(agent, None)
    rebuild.assert_not_called()
    assert agent.llm is live


@pytest.mark.asyncio
async def test_cleared_key_drops_the_live_client_and_a_new_key_rebuilds(
        tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
            'modelscope_api_key': 'sk-SENTINEL-OLD',
            'api_key': 'sk-SENTINEL-OLD',
        },
    })
    live = SimpleNamespace(
        config=config,
        model='Qwen/Qwen3.8-Flash-Next',
        client=SimpleNamespace(api_key='sk-SENTINEL-OLD'),
        _setup_stub=False,
    )
    memory = SimpleNamespace(llm=live, set_llm=lambda llm: setattr(
        memory, 'seen', llm))
    agent = SimpleNamespace(
        config=config,
        llm=live,
        runtime=SimpleNamespace(llm=live),
        memory_tools=[memory],
        _skill_runtime=None,
        mcp_runtime=None,
        _llm_fp='stale',
    )

    class _KeyError(Exception):
        pass

    _KeyError.__name__ = 'OpenAIError'

    class Rebuilt:
        def __init__(self):
            self.model = 'Qwen/Qwen3.8-Flash-Next'
            self.config = config
            self.client = SimpleNamespace(api_key='sk-SENTINEL-NEW')
            self._setup_stub = False

    with patch('ms_agent.llm.LLM.from_config',
               side_effect=_KeyError(
                   'The api_key client option must be set')):
        await apply_live_config(agent, None)
    assert agent.llm is not live
    assert agent.llm._setup_stub is True
    assert agent.runtime.llm is agent.llm
    assert agent.llm.config is config
    assert not hasattr(agent.llm, 'client')
    assert memory.seen is None

    config.llm.modelscope_api_key = 'sk-SENTINEL-NEW'
    config.llm.api_key = 'sk-SENTINEL-NEW'
    with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
        await apply_live_config(agent, None)
    assert agent.llm.client.api_key == 'sk-SENTINEL-NEW'
    assert agent.runtime.llm.client.api_key == 'sk-SENTINEL-NEW'
    assert memory.seen is agent.llm


@pytest.mark.asyncio
async def test_unrelated_rebuild_error_keeps_the_live_client(
        tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
            'modelscope_api_key': 'sk-SENTINEL-OLD',
        },
    })
    live = SimpleNamespace(
        config=config,
        client=SimpleNamespace(api_key='sk-SENTINEL-OLD'),
        _setup_stub=False,
    )
    agent = SimpleNamespace(
        config=config,
        llm=live,
        runtime=SimpleNamespace(llm=live),
        memory_tools=[],
        _skill_runtime=None,
        mcp_runtime=None,
        _llm_fp='stale',
    )
    with patch('ms_agent.llm.LLM.from_config',
               side_effect=RuntimeError('catalog down')):
        await apply_live_config(agent, None)
    assert agent.llm is live
    assert agent.llm.client.api_key == 'sk-SENTINEL-OLD'


def test_missing_key_error_is_the_setup_sentence():
    from ms_agent.llm.credentials import (
        client_rejected_missing_key, is_missing_api_key_error,
        missing_api_key_error)
    config = OmegaConf.create({'llm': {'service': 'modelscope'}})
    err = missing_api_key_error(config)
    assert is_missing_api_key_error(err)
    assert 'modelscope' in str(err)

    class _KeyError(Exception):
        pass

    _KeyError.__name__ = 'OpenAIError'
    assert client_rejected_missing_key(
        _KeyError('The api_key client option must be set'))
    assert not client_rejected_missing_key(RuntimeError('api_key'))
    assert not client_rejected_missing_key(_KeyError('connection reset'))


def _quiet_agent(tmp_path, **extra):
    config = OmegaConf.create({'output_dir': str(tmp_path)})
    agent = SimpleNamespace(
        config=config,
        llm=None,
        runtime=SimpleNamespace(),
        memory_tools=[],
        _skill_runtime=None,
        mcp_runtime=None,
        tool_manager=None,
        _llm_fp=None,
        _mcp_fp=None,
        _search_fp=None,
        _live_notice_keys=set(),
        notices=[],
    )
    agent._emit_user_notice = agent.notices.append
    for key, value in extra.items():
        setattr(agent, key, value)
    return agent


@pytest.mark.asyncio
async def test_bad_json_is_said_once(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    (tmp_path / 'mcp.json').write_text('{', encoding='utf-8')
    agent = _quiet_agent(tmp_path)
    await apply_live_config(agent, None)
    await apply_live_config(agent, None)
    assert agent.notices == ['mcp.json 读不进去。请检查格式。']


@pytest.mark.asyncio
async def test_pending_mcp_reconnects_when_the_file_is_unchanged(
        tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    from ms_agent.tui.live_config import _token

    class Runtime:
        def __init__(self):
            self.calls = 0

        async def apply_config(self, config):
            del config
            self.calls += 1

        def get_server(self, name):
            del name
            return SimpleNamespace(status='connected')

    runtime = Runtime()
    agent = _quiet_agent(
        tmp_path,
        mcp_runtime=runtime,
        _mcp_fp=_token({}),
        _mcp_reconnect_names={'fetch'},
    )
    await apply_live_config(agent, None)
    await apply_live_config(agent, None)
    assert runtime.calls == 1
    assert agent.notices == []
    assert agent._mcp_reconnect_names == set()


@pytest.mark.asyncio
async def test_failed_mcp_reconnect_is_said_once(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    from ms_agent.tui.live_config import _token

    class Runtime:
        def __init__(self):
            self.calls = 0

        async def apply_config(self, config):
            del config
            self.calls += 1

        def get_server(self, name):
            del name
            return SimpleNamespace(status='error')

    runtime = Runtime()
    agent = _quiet_agent(
        tmp_path,
        mcp_runtime=runtime,
        _mcp_fp=_token({}),
        _mcp_reconnect_names={'fetch'},
    )
    await apply_live_config(agent, None)
    await apply_live_config(agent, None)
    assert runtime.calls == 1
    assert agent.notices == []


@pytest.mark.asyncio
async def test_unreachable_server_is_skipped_before_the_turn(
        tmp_path, monkeypatch):
    import asyncio
    import json

    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setattr('ms_agent.mcp.runtime.MCP_TURN_WAIT', 0.05)
    (tmp_path / 'mcp.json').write_text(
        json.dumps({
            'mcpServers': {
                'slow': {'command': 'sleep', 'args': ['30']},
                'good': {'command': 'echo', 'args': ['hi']},
            },
        }),
        encoding='utf-8',
    )
    from ms_agent.config.mcp_schema import ResolvedMCPConfig
    from ms_agent.mcp.runtime import MCPRuntime

    class Hung:
        def __init__(self):
            self.sessions = {}
            self.connect_calls: list[str] = []

        def is_connected(self, name):
            return name in self.sessions

        async def connect_single_server(self, server_name, server_config, **kwargs):
            self.connect_calls.append(server_name)
            if server_name == 'slow':
                await asyncio.Event().wait()
            self.sessions[server_name] = object()
            return server_name

        async def disconnect_server(self, server_name, **kwargs):
            self.sessions.pop(server_name, None)

        async def get_tools_for_server(self, server_name):
            return []

    client = Hung()
    runtime = MCPRuntime(
        mcp_client=client,  # type: ignore[arg-type]
        config=ResolvedMCPConfig(mcp_servers={}),
        owns_client=False,
    )
    agent = _quiet_agent(tmp_path, mcp_runtime=runtime)
    started = asyncio.get_running_loop().time()
    try:
        await apply_live_config(agent, None)
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 0.5
        assert runtime.get_server('slow').status == 'connecting'
        assert runtime.get_server('good').status == 'connected'
        assert agent.notices == []
        await apply_live_config(agent, None)
        assert client.connect_calls.count('slow') == 1
        assert agent.notices == []
    finally:
        await runtime._cancel_probes()


@pytest.mark.asyncio
async def test_memory_toggle_applies_on_the_next_message(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    work = tmp_path / 'work'
    work.mkdir()
    from ms_agent.project import ProjectManager
    ProjectManager(base_dir=str(home)).open_folder(
        str(work), memory_enabled=True, memory_backend='file')
    agent = _quiet_agent(work)
    agent.runtime._memory_pending = True

    async def load_memory():
        agent.memory_tools.append(object())

    agent.load_memory = load_memory
    await apply_live_config(agent, None)
    assert agent.config.memory.unified_memory.storage.backend == 'file'
    assert agent.memory_tools
    assert agent.runtime._memory_pending is False


@pytest.mark.asyncio
async def test_search_engine_reloads_on_the_next_message(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    from ms_agent.config.search_settings import SearchSettingsManager

    SearchSettingsManager(tmp_path).set_engine('arxiv')

    class Tool:
        SERVER_NAME = 'web_search'
        _engine_types = ['tavily']
        _api_keys = {}
        _engines = {'tavily': object()}

        def __init__(self):
            self.reloaded = False

        async def reload_from_config(self):
            self.reloaded = True
            self._engine_types = ['arxiv']

    tool = Tool()
    agent = _quiet_agent(tmp_path)
    agent.tool_manager = SimpleNamespace(extra_tools=[tool])
    await apply_live_config(agent, None)
    assert tool.reloaded is True
