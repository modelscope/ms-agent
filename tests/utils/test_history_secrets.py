# Copyright (c) ModelScope Contributors. All rights reserved.
"""History yaml must not keep API keys or MCP Authorization."""
from __future__ import annotations

import json

from omegaconf import OmegaConf

from ms_agent.llm.utils import Message
from ms_agent.utils.constants import DEFAULT_MEMORY_DIR
from ms_agent.utils.utils import read_history, save_history


def _messages():
    return [
        Message(role='system', content='sys'),
        Message(role='user', content='hello'),
    ]


def test_save_history_strips_keys_and_leaves_memory_intact(tmp_path):
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
            'api_key': 'sk-live-secret-value-1234',
            'base_url': 'https://api.example/v1?api_key=sk-query-secret',
        },
        '_merged_mcp': {
            'servers': {
                'remote': {
                    'url': 'https://mcp.example/rpc',
                    'headers': {
                        'Authorization': 'Bearer secret-token',
                        'Content-Type': 'application/json',
                    },
                },
            },
        },
    })
    save_history(str(tmp_path), 'Agent-default', config, _messages())
    text = (tmp_path / DEFAULT_MEMORY_DIR / 'Agent-default.yaml').read_text()
    assert 'sk-live-secret-value-1234' not in text
    assert 'secret-token' not in text
    assert 'sk-query-secret' not in text
    assert '***' not in text
    assert 'Content-Type' in text
    assert 'Qwen/Qwen3.8-Flash-Next' in text
    assert config.llm.api_key == 'sk-live-secret-value-1234'
    loaded, messages = read_history(str(tmp_path), 'Agent-default')
    assert loaded.llm.api_key in (None, '')
    assert messages[-1].content == 'hello'


def test_legacy_read_refills_keys_from_settings_and_mcp(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    (home / 'settings.json').write_text(
        json.dumps({
            'providers': {
                'modelscope': {
                    'api_key': 'sk-from-settings',
                    'base_url': 'https://api.example/v1',
                },
            },
        }))
    project = tmp_path / 'proj'
    mcp_dir = project / '.ms_agent'
    mcp_dir.mkdir(parents=True)
    (mcp_dir / 'mcp.json').write_text(
        json.dumps({
            'mcpServers': {
                'remote': {
                    'url': 'https://mcp.example/rpc',
                    'headers': {
                        'Authorization': 'Bearer from-mcp',
                        'Content-Type': 'application/json',
                    },
                },
            },
        }))
    config = OmegaConf.create({
        'llm': {
            'service': 'modelscope',
            'model': 'Qwen/Qwen3.8-Flash-Next',
            'api_key': 'sk-live-secret-value-1234',
        },
        '_merged_mcp': {
            'servers': {
                'remote': {
                    'headers': {
                        'Authorization': 'Bearer secret-token',
                    },
                },
            },
        },
        'output_dir': str(project),
    })
    save_history(str(project), 'Agent-default', config, _messages())
    disk = (project / DEFAULT_MEMORY_DIR / 'Agent-default.yaml').read_text()
    assert 'sk-from-settings' not in disk
    assert 'from-mcp' not in disk

    from ms_agent.agent.llm_agent import LLMAgent
    agent = LLMAgent.__new__(LLMAgent)
    agent.output_dir = str(project)
    agent.tag = 'Agent-default'
    agent.load_cache = True
    agent.config = OmegaConf.create({'llm': {'service': 'other'}})
    agent.runtime = None
    agent.llm = None
    agent.mcp_runtime = None
    loaded, _runtime, messages = agent.read_history(_messages())
    assert loaded.llm.api_key == 'sk-from-settings'
    assert loaded.llm.model == 'Qwen/Qwen3.8-Flash-Next'
    headers = loaded._merged_mcp.servers.remote.headers
    assert headers.Authorization == 'Bearer from-mcp'
    assert messages[-1].content == 'hello'
    assert 'from-mcp' not in disk
