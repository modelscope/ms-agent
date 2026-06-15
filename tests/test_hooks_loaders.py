"""Tests for multi-platform hook loaders."""

from __future__ import annotations

import json
from pathlib import Path

from ms_agent.hooks.loaders.claude import ClaudeSettingsLoader
from ms_agent.hooks.loaders.cursor import CursorHooksLoader
from ms_agent.hooks.loaders.hermes import HermesShellLoader
from ms_agent.hooks.loaders.native import NativeJsonLoader, NativeYamlLoader


class TestClaudeLoader:
    def test_pre_tool_use(self, tmp_path):
        settings = {
            'hooks': {
                'PreToolUse': [{
                    'matcher': 'Bash',
                    'hooks': [{
                        'type': 'command',
                        'command': './hooks/check.sh',
                    }],
                }],
            },
        }
        path = tmp_path / 'settings.json'
        path.write_text(json.dumps(settings))
        reg = ClaudeSettingsLoader.load_file(path, str(tmp_path))
        handlers = reg.get_handlers(
            'PreToolUse', 'code_executor---shell_executor')
        assert len(handlers) == 1
        assert handlers[0].command == './hooks/check.sh'


class TestCursorLoader:
    def test_pre_tool_use(self, tmp_path):
        data = {
            'hooks': {
                'preToolUse': [{
                    'command': './cursor-hook.sh',
                    'matcher': 'Shell',
                }],
            },
        }
        path = tmp_path / 'hooks.json'
        path.write_text(json.dumps(data))
        reg = CursorHooksLoader.load_file(path, str(tmp_path))
        handlers = reg.get_handlers(
            'PreToolUse', 'code_executor---shell_executor')
        assert len(handlers) == 1


class TestHermesLoader:
    def test_pre_tool_call(self, tmp_path):
        import yaml
        data = {
            'hooks': {
                'pre_tool_call': [{
                    'command': './hermes-hook.sh',
                    'matcher': 'terminal',
                }],
            },
        }
        path = tmp_path / 'config.yaml'
        path.write_text(yaml.dump(data))
        reg = HermesShellLoader.load_file(path, str(tmp_path))
        handlers = reg.get_handlers(
            'PreToolUse', 'code_executor---shell_executor')
        assert len(handlers) == 1


class TestNativeLoader:
    def test_yaml(self, tmp_path):
        import yaml
        data = {'hooks': {'Stop': [{'hooks': [
            {'type': 'command', 'command': 'cleanup.sh'},
        ]}]}}
        path = tmp_path / 'hooks.yaml'
        path.write_text(yaml.dump(data))
        reg = NativeYamlLoader.load_file(path)
        assert len(reg.get_handlers('Stop')) == 1

    def test_json(self, tmp_path):
        data = {'hooks': {'SessionStart': [{'hooks': [
            {'type': 'command', 'command': 'init.sh'},
        ]}]}}
        path = tmp_path / 'hooks.json'
        path.write_text(json.dumps(data))
        reg = NativeJsonLoader.load_file(path)
        assert len(reg.get_handlers('SessionStart')) == 1
