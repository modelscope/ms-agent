# Copyright (c) ModelScope Contributors. All rights reserved.
"""Regression coverage for capability adapters, without external model calls."""
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ms_agent.capabilities import create_registry
from ms_agent.capabilities.async_task import AsyncTaskManager
from ms_agent.capabilities.wrappers import (agent_delegate, lsp_code_server,
                                            web_search)


def test_delegate_missing_config_does_not_fall_back_or_download(tmp_path):
    from ms_agent.config.config import Config

    with patch.object(Config, 'from_task') as load:
        with pytest.raises(
                FileNotFoundError, match='Agent config file not found'):
            agent_delegate._build_agent_config(str(tmp_path / 'missing.yaml'))
        load.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancelled', [False, True])
async def test_delegate_config_credentials_stdout_and_cleanup(
        monkeypatch, tmp_path, cancelled):
    """Configured providers must work without unrelated environment keys."""
    from ms_agent.agent import llm_agent

    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('MODELSCOPE_API_KEY', raising=False)
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / 'agent.yaml'
    config_path.write_text(
        'llm:\n  service: anthropic\n  model: test-model\n'
        '  api_key: test-config-key\n',
        encoding='utf-8')
    stdout = sys.stdout
    cleaned = []

    class Agent:
        tool_manager = object()

        def __init__(self, config, tag):
            assert config.llm.service == 'anthropic'
            assert config.llm.api_key == 'test-config-key'

        async def run(self, query):
            assert sys.stdout is stdout
            if cancelled:
                raise asyncio.CancelledError()
            return [SimpleNamespace(role='assistant', content='done')]

        async def cleanup_tools(self):
            assert sys.stdout is stdout
            cleaned.append(True)

    monkeypatch.setattr(llm_agent, 'LLMAgent', Agent)
    args = {'query': 'test', 'config_path': str(config_path)}
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await create_registry().invoke('delegate_task', args)
    else:
        result = await create_registry().invoke('delegate_task', args)
        assert result == {'status': 'completed', 'response': 'done'}
    assert cleaned == [True]
    assert sys.stdout is stdout


@pytest.mark.asyncio
async def test_background_delegate_accepts_provider_configuration(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('MODELSCOPE_API_KEY', raising=False)
    manager = AsyncTaskManager()
    monkeypatch.setattr(agent_delegate, '_manager', manager)

    async def run_agent(**kwargs):
        assert kwargs['config_path'] == 'custom-provider.yaml'
        return 'configured provider result'

    monkeypatch.setattr(agent_delegate, '_run_agent', run_agent)
    result = await create_registry().invoke(
        'submit_agent_task', {
            'query': 'test',
            'config_path': 'custom-provider.yaml'
        })
    task = manager.get(result['task_id'])
    await task._asyncio_task
    assert manager.get_result(
        task.task_id)['result']['response'] == ('configured provider result')


@pytest.mark.asyncio
async def test_research_submit_accepts_configured_credentials(
        monkeypatch, tmp_path):
    from ms_agent.capabilities.wrappers import deep_research

    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    manager = AsyncTaskManager()
    monkeypatch.setattr(deep_research, '_manager', manager)
    config = tmp_path / 'researcher.yaml'
    config.write_text('llm:\n  service: openai\n  openai_api_key: test-key\n')

    async def research(task):
        assert task.metadata['config_path'] == str(config)
        return {'report_path': 'report.md'}

    monkeypatch.setattr(deep_research, '_background_research', research)
    result = await create_registry().invoke(
        'submit_research_task', {
            'query': 'test',
            'config_path': str(config),
            'output_dir': str(tmp_path / 'result')
        })
    task = manager.get(result['task_id'])
    await task._asyncio_task
    assert manager.get_result(task.task_id)['status'] == 'completed'


@pytest.mark.asyncio
@pytest.mark.parametrize('key_name', ['EXA_API_KEY', 'EXA_API_KEYS'])
async def test_exa_accepts_single_key_or_key_pool(monkeypatch, key_name):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.delenv('EXA_API_KEYS', raising=False)
    monkeypatch.setenv(key_name, 'test-key-one,test-key-two')
    initialized = []

    class Engine:

        @staticmethod
        def build_request_from_args(**kwargs):
            return kwargs

        def search(self, request):
            assert request == {'query': 'test', 'num_results': 1}
            return SimpleNamespace(to_list=lambda: [{
                'title': 'test result',
                'url': 'https://example.com',
                'summary': 'test summary'
            }])

    def get_engine(engine_type):
        initialized.append(engine_type)
        return Engine()

    monkeypatch.setattr(web_search, '_get_engine', get_engine)
    result = await create_registry().invoke('web_search', {
        'query': 'test',
        'engine_type': ' ExA ',
        'num_results': 1
    })
    assert result['status'] == 'ok'
    assert result['engine'] == 'exa'
    assert result['count'] == 1
    assert initialized == ['exa']


@pytest.mark.asyncio
async def test_exa_missing_credentials_lists_both_options(monkeypatch):
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    monkeypatch.setenv('EXA_API_KEYS', '')
    with patch.object(web_search, '_get_engine') as initialize:
        result = await create_registry().invoke('web_search', {
            'query': 'test',
            'engine_type': 'exa'
        })
    initialize.assert_not_called()
    assert 'EXA_API_KEY' in result['error']
    assert 'EXA_API_KEYS' in result['error']


@pytest.mark.parametrize('available', [True, False])
def test_typescript_preflight_checks_npx_not_global_server(
        monkeypatch, available):
    monkeypatch.setattr(
        lsp_code_server.shutil, 'which', lambda name: '/test/bin/npx'
        if name == 'npx' and available else None)
    result = lsp_code_server._check_language_backend('typescript')
    if available:
        assert result is None
    else:
        assert 'npx' in result['error']
        assert 'Node.js' in result['error']


@pytest.mark.asyncio
@pytest.mark.parametrize('capability',
                         ['lsp_check_directory', 'lsp_update_and_check'])
async def test_typescript_local_install_reaches_backend(
        monkeypatch, tmp_path, capability):
    monkeypatch.setattr(
        lsp_code_server.shutil, 'which', lambda name: '/test/bin/npx'
        if name == 'npx' else None)
    calls = []

    async def call_tool(server_name, *, tool_name, tool_args):
        calls.append((server_name, tool_name, tool_args))
        return 'local backend result'

    def get_server(workspace):
        assert workspace == str(tmp_path)
        return SimpleNamespace(call_tool=call_tool)

    monkeypatch.setattr(lsp_code_server, '_get_lsp_server', get_server)
    args = {'language': 'typescript'}
    if capability == 'lsp_check_directory':
        args['directory'] = str(tmp_path)
    else:
        args.update(file_path=str(tmp_path / 'main.ts'), content='export {};')
    result = await create_registry().invoke(capability, args)
    assert result == {'result': 'local backend result'}
    assert len(calls) == 1
    assert calls[0][2]['language'] == 'typescript'


def test_java_backend_uses_supported_install_locations():
    with patch.object(lsp_code_server.shutil, 'which', return_value=None), \
            patch.object(lsp_code_server.os.path, 'isfile',
                         side_effect=lambda path: path == '/opt/homebrew/bin/jdtls'):
        assert lsp_code_server._check_language_backend('java') is None


@pytest.mark.asyncio
async def test_mcp_stdio_survives_concurrent_tool_output(tmp_path):
    """Exercise real JSON-RPC framing while concurrent tools print to stdout."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    script = '''
import asyncio
from ms_agent.capabilities import CapabilityDescriptor, CapabilityRegistry
from ms_agent.capabilities import mcp_server
registry = CapabilityRegistry()
async def noisy(args, **kwargs):
    print('tool output before await')
    await asyncio.sleep(0.02)
    print('tool output after await')
    return {'value': args['value']}
registry.register(CapabilityDescriptor(
    name='noisy', version='0.1.0', granularity='tool', summary='test', description='test',
    input_schema={'type': 'object', 'properties': {'value': {'type': 'integer'}},
                  'required': ['value']}), noisy)
mcp_server.create_registry = lambda: registry
mcp_server.main()
'''
    repo = str(Path(__file__).resolve().parents[2])
    params = StdioServerParameters(
        command=sys.executable,
        args=['-c', script],
        env={
            **os.environ, 'PYTHONPATH': repo,
            'MS_AGENT_HOME': str(tmp_path / 'home')
        })
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            results = await asyncio.gather(
                *(session.call_tool('noisy', {'value': i}) for i in range(3)))
            assert [json.loads(r.content[0].text)['value']
                    for r in results] == [0, 1, 2]
            assert not any(r.isError for r in results)
            assert len((await session.list_tools()).tools) == 1


@pytest.mark.asyncio
async def test_http_handler_does_not_replace_stdout():
    from ms_agent.capabilities.mcp_server import _build_handler

    registry = create_registry()
    handler = _build_handler(registry, registry.get('lsp_code_server'), '.')
    stdout = sys.stdout
    result = json.loads(await handler())
    assert result['component'] == 'lsp_code_server'
    assert sys.stdout is stdout


def test_http_server_honors_port(monkeypatch):
    from mcp.server import fastmcp
    from ms_agent.capabilities import mcp_server

    recorded = {}

    class Server:

        def __init__(self, name, **kwargs):
            recorded.update(kwargs)

        def tool(self, **kwargs):
            return lambda fn: fn

        def run(self, *, transport):
            recorded['transport'] = transport

    monkeypatch.setattr(fastmcp, 'FastMCP', Server)
    monkeypatch.setattr(mcp_server, '_load_env', lambda _: None)
    monkeypatch.setattr(
        sys, 'argv',
        ['mcp_server', '--transport', 'streamable-http', '--port', '9876'])
    mcp_server.main()
    assert recorded['port'] == 9876
    assert recorded['transport'] == 'streamable-http'
