"""Comprehensive ACP protocol correctness and rendering tests.

Tests cover:
  1. Translator rendering: edit/read/execute tool calls produce correct ACP
     content types (diff, locations, specialized starts)
  2. Multi-message delta tracking: all messages (including tool results)
     are captured, not just the last one
  3. Plan update extraction from todo_write results
  4. Permission schema correctness
  5. Full message flow simulation (assistant -> tool_call -> tool_result)
  6. Error detection in tool results
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from ms_agent.acp.translator import (
    ACPTranslator,
    _build_title,
    _extract_locations,
    _infer_kind_from_args,
    _parse_tool_args,
    _try_parse_diff_from_result,
)
from ms_agent.llm.utils import Message


class TestToolArgParsing:

    def test_parse_valid_json(self):
        args = _parse_tool_args('{"path": "/src/main.py", "content": "hello"}')
        assert args['path'] == '/src/main.py'
        assert args['content'] == 'hello'

    def test_parse_empty(self):
        assert _parse_tool_args('') == {}
        assert _parse_tool_args(None) == {}

    def test_parse_invalid_json(self):
        assert _parse_tool_args('not json') == {}

    def test_parse_non_dict(self):
        assert _parse_tool_args('"just a string"') == {}


class TestKindInference:

    def test_known_tools(self):
        assert _infer_kind_from_args('code_executor', {}) == 'execute'
        assert _infer_kind_from_args('web_search', {}) == 'search'
        assert _infer_kind_from_args('file_write', {}) == 'edit'
        assert _infer_kind_from_args('todo', {}) == 'think'

    def test_filesystem_method_dispatch(self):
        assert _infer_kind_from_args(
            'filesystem', {'method': 'write_file'}) == 'edit'
        assert _infer_kind_from_args(
            'filesystem', {'method': 'read_file'}) == 'read'
        assert _infer_kind_from_args(
            'filesystem', {'method': 'list_files'}) == 'read'
        assert _infer_kind_from_args(
            'filesystem', {'method': 'replace_file_contents'}) == 'edit'

    def test_name_heuristic(self):
        assert _infer_kind_from_args('my_custom_write_tool', {}) == 'edit'
        assert _infer_kind_from_args('grep_search_tool', {}) == 'search'
        assert _infer_kind_from_args('run_shell_command', {}) == 'execute'
        assert _infer_kind_from_args('delete_file', {}) == 'delete'
        assert _infer_kind_from_args('rename_file', {}) == 'move'
        assert _infer_kind_from_args('fetch_url', {}) == 'fetch'
        assert _infer_kind_from_args('plan_steps', {}) == 'think'

    def test_unknown_tool(self):
        assert _infer_kind_from_args('totally_unknown_xyz', {}) == 'other'


class TestTitleBuilding:

    def test_edit_with_path(self):
        title = _build_title('file_write', {'path': '/src/main.py'}, 'edit')
        assert title == 'Edit /src/main.py'

    def test_read_with_path(self):
        title = _build_title('file_read', {'path': '/src/config.json'}, 'read')
        assert title == 'Read /src/config.json'

    def test_execute_with_code(self):
        title = _build_title('code_executor',
                             {'code': 'print("hello world")\nprint("done")'}, 'execute')
        assert 'print("hello world")' in title
        assert title.startswith('Run:')

    def test_search_with_query(self):
        title = _build_title('web_search', {'query': 'quantum computing'}, 'search')
        assert 'quantum computing' in title

    def test_fallback_to_tool_name(self):
        title = _build_title('my_custom_tool', {}, 'other')
        assert title == 'my_custom_tool'


class TestLocationExtraction:

    def test_extract_from_path(self):
        locs = _extract_locations({'path': '/src/main.py'})
        assert locs is not None
        assert len(locs) == 1
        assert locs[0].path == '/src/main.py'
        assert locs[0].line is None

    def test_extract_with_line(self):
        locs = _extract_locations({'path': '/src/main.py', 'line': 42})
        assert locs[0].line == 42

    def test_extract_from_file_path(self):
        locs = _extract_locations({'file_path': '/src/utils.py'})
        assert locs[0].path == '/src/utils.py'

    def test_no_path(self):
        assert _extract_locations({}) is None
        assert _extract_locations({'query': 'test'}) is None


class TestDiffExtraction:

    def test_write_file(self):
        diff = _try_parse_diff_from_result(
            'file_write',
            {'path': '/src/main.py', 'content': 'def hello(): pass'},
            'Save file successfully',
        )
        assert diff is not None
        assert diff['path'] == '/src/main.py'
        assert diff['new_text'] == 'def hello(): pass'
        assert diff['old_text'] is None

    def test_replace_file_contents(self):
        diff = _try_parse_diff_from_result(
            'replace_file_contents',
            {'path': '/src/main.py', 'source': 'old code', 'target': 'new code'},
            'Replaced successfully',
        )
        assert diff is not None
        assert diff['old_text'] == 'old code'
        assert diff['new_text'] == 'new code'

    def test_file_operation_write(self):
        diff = _try_parse_diff_from_result(
            'filesystem',
            {'path': '/data.txt', 'method': 'write', 'content': 'data'},
            'OK',
        )
        assert diff is not None
        assert diff['new_text'] == 'data'

    def test_no_path_returns_none(self):
        diff = _try_parse_diff_from_result(
            'file_write', {}, 'OK')
        assert diff is None

    def test_no_matching_method_returns_none(self):
        diff = _try_parse_diff_from_result(
            'file_read', {'path': '/src/main.py', 'method': 'read'}, 'content')
        assert diff is None


class TestTranslatorEdits:
    """Test that file edit tool calls produce proper ACP start_edit_tool_call."""

    def test_file_write_produces_edit_start(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_write_1',
            'tool_name': 'file_write',
            'arguments': json.dumps({
                'path': '/src/main.py',
                'content': 'def hello(): pass',
            }),
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        updates = t.messages_to_updates(msgs)

        tool_starts = [u for u in updates if hasattr(u, 'tool_call_id')
                       and hasattr(u, 'session_update')
                       and u.session_update == 'tool_call']
        assert len(tool_starts) == 1
        start = tool_starts[0]
        assert start.tool_call_id == 'tc_write_1'
        assert start.kind == 'edit'
        assert 'Edit' in start.title

    def test_file_read_produces_read_start(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_read_1',
            'tool_name': 'file_read',
            'arguments': json.dumps({'path': '/src/config.json'}),
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        updates = t.messages_to_updates(msgs)

        tool_starts = [u for u in updates if hasattr(u, 'tool_call_id')
                       and getattr(u, 'session_update', '') == 'tool_call']
        assert len(tool_starts) == 1
        start = tool_starts[0]
        assert start.kind == 'read'
        assert 'Read' in start.title

    def test_code_execute_produces_execute_start(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_exec_1',
            'tool_name': 'code_executor',
            'arguments': json.dumps({'code': 'print("hello")'}),
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        updates = t.messages_to_updates(msgs)

        tool_starts = [u for u in updates
                       if getattr(u, 'session_update', '') == 'tool_call']
        assert len(tool_starts) == 1
        start = tool_starts[0]
        assert start.kind == 'execute'
        assert 'Run:' in start.title or 'Execute' in start.title

    def test_search_tool_produces_search_start(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_search_1',
            'tool_name': 'web_search',
            'arguments': json.dumps({'query': 'quantum computing'}),
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        updates = t.messages_to_updates(msgs)

        tool_starts = [u for u in updates
                       if getattr(u, 'session_update', '') == 'tool_call']
        assert len(tool_starts) == 1
        start = tool_starts[0]
        assert start.kind == 'search'
        assert 'quantum computing' in start.title


class TestTranslatorToolResults:
    """Test that tool results produce correct content types."""

    def test_file_write_result_with_diff(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_w1',
            'tool_name': 'file_write',
            'arguments': json.dumps({
                'path': '/src/main.py', 'content': 'def hello(): pass'
            }),
        }
        msgs_assistant = [Message(role='assistant', content='', tool_calls=[tc])]
        t.messages_to_updates(msgs_assistant)

        msgs_tool = [
            Message(role='assistant', content='', tool_calls=[tc]),
            Message(role='tool', content='Save file successfully',
                    tool_call_id='tc_w1', name='file_write'),
        ]
        updates = t.messages_to_updates(msgs_tool)

        tool_updates = [u for u in updates
                        if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(tool_updates) == 1
        tu = tool_updates[0]
        assert tu.status == 'completed'
        assert tu.content is not None
        has_diff = any(
            getattr(c, 'type', '') == 'diff' for c in tu.content)
        assert has_diff, 'File write should produce a diff content item'

    def test_error_result_sets_failed_status(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_err',
            'tool_name': 'code_executor',
            'arguments': '{"code": "raise Exception()"}',
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        t.messages_to_updates(msgs)

        msgs2 = [
            Message(role='assistant', content='', tool_calls=[tc]),
            Message(role='tool',
                    content='Error: Traceback (most recent call last)...',
                    tool_call_id='tc_err', name='code_executor'),
        ]
        updates = t.messages_to_updates(msgs2)
        tool_updates = [u for u in updates
                        if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(tool_updates) == 1
        assert tool_updates[0].status == 'failed'

    def test_success_result_sets_completed_status(self):
        t = ACPTranslator()
        tc = {
            'id': 'tc_ok',
            'tool_name': 'web_search',
            'arguments': '{"query": "test"}',
        }
        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        t.messages_to_updates(msgs)

        msgs2 = [
            Message(role='assistant', content='', tool_calls=[tc]),
            Message(role='tool',
                    content='Found 5 results about test...',
                    tool_call_id='tc_ok', name='web_search'),
        ]
        updates = t.messages_to_updates(msgs2)
        tool_updates = [u for u in updates
                        if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(tool_updates) == 1
        assert tool_updates[0].status == 'completed'


class TestMultiMessageTracking:
    """Ensure the translator processes ALL new messages, not just the last."""

    def test_processes_multiple_tool_results(self):
        t = ACPTranslator()
        tc1 = {'id': 'tc_a', 'tool_name': 'web_search',
               'arguments': '{"query":"a"}'}
        tc2 = {'id': 'tc_b', 'tool_name': 'web_search',
               'arguments': '{"query":"b"}'}

        msgs = [
            Message(role='assistant', content='Searching...',
                    tool_calls=[tc1, tc2]),
        ]
        u1 = t.messages_to_updates(msgs)
        assert len([u for u in u1
                    if getattr(u, 'session_update', '') == 'tool_call']) == 2

        msgs.append(Message(role='tool', content='Result A',
                            tool_call_id='tc_a', name='web_search'))
        msgs.append(Message(role='tool', content='Result B',
                            tool_call_id='tc_b', name='web_search'))
        u2 = t.messages_to_updates(msgs)

        tool_updates = [u for u in u2
                        if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(tool_updates) == 2, (
            f'Expected 2 tool_call_updates, got {len(tool_updates)}')

    def test_assistant_deltas_tracked_across_chunks(self):
        t = ACPTranslator()
        msgs = [Message(role='assistant', content='He')]
        u1 = t.messages_to_updates(msgs)
        text_updates_1 = [u for u in u1
                          if getattr(u, 'session_update', '') == 'agent_message_chunk']
        assert len(text_updates_1) == 1

        msgs[0] = Message(role='assistant', content='Hello world')
        u2 = t.messages_to_updates(msgs)
        text_updates_2 = [u for u in u2
                          if getattr(u, 'session_update', '') == 'agent_message_chunk']
        assert len(text_updates_2) == 1

    def test_no_duplicate_tool_call_starts(self):
        t = ACPTranslator()
        tc = {'id': 'tc_dup', 'tool_name': 'web_search',
              'arguments': '{"query": "test"}'}

        msgs = [Message(role='assistant', content='', tool_calls=[tc])]
        u1 = t.messages_to_updates(msgs)
        starts_1 = [u for u in u1
                    if getattr(u, 'session_update', '') == 'tool_call']
        assert len(starts_1) == 1

        u2 = t.messages_to_updates(msgs)
        starts_2 = [u for u in u2
                    if getattr(u, 'session_update', '') == 'tool_call']
        assert len(starts_2) == 0

    def test_no_duplicate_tool_completions(self):
        t = ACPTranslator()
        tc = {'id': 'tc_nodupe', 'tool_name': 'web_search',
              'arguments': '{}'}
        msgs = [
            Message(role='assistant', content='', tool_calls=[tc]),
            Message(role='tool', content='result',
                    tool_call_id='tc_nodupe', name='web_search'),
        ]
        u1 = t.messages_to_updates(msgs)
        completions_1 = [u for u in u1
                         if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(completions_1) == 1

        u2 = t.messages_to_updates(msgs)
        completions_2 = [u for u in u2
                         if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(completions_2) == 0


class TestPlanUpdates:
    """Test plan extraction from todo tool results."""

    def test_extract_from_todo_write_output(self):
        from ms_agent.acp.server import MSAgentACPServer

        todo_result = json.dumps({
            'status': 'ok',
            'plan_path': 'plan.json',
            'todos': [
                {'id': 'T1', 'content': 'Search papers', 'status': 'in_progress',
                 'priority': 'high'},
                {'id': 'T2', 'content': 'Analyze results', 'status': 'pending',
                 'priority': 'medium'},
                {'id': 'T3', 'content': 'Write report', 'status': 'pending',
                 'priority': 'medium'},
            ],
        })

        session = MagicMock()
        session.agent.runtime = None
        session.messages = [
            Message(role='user', content='Research quantum computing'),
            Message(role='assistant', content='', tool_calls=[
                {'id': 'tc_todo', 'tool_name': 'todo_write', 'arguments': '{}'}
            ]),
            Message(role='tool', content=todo_result,
                    tool_call_id='tc_todo', name='todo_write'),
        ]

        translator = ACPTranslator()
        plans = MSAgentACPServer._extract_plan_updates(session, translator)
        assert len(plans) == 1
        plan = plans[0]
        assert hasattr(plan, 'entries')
        assert len(plan.entries) == 3
        assert plan.entries[0].content == 'Search papers'

    def test_no_plan_when_no_todos(self):
        from ms_agent.acp.server import MSAgentACPServer

        session = MagicMock()
        session.agent.runtime = None
        session.messages = [
            Message(role='user', content='Hello'),
            Message(role='assistant', content='Hi there!'),
        ]

        translator = ACPTranslator()
        plans = MSAgentACPServer._extract_plan_updates(session, translator)
        assert plans == []


class TestPermissionSchema:
    """Test permission response format matches ACP schema."""

    def test_auto_approve_returns_valid_response(self):
        from ms_agent.acp.client import _CollectorClient
        from acp.schema import (
            PermissionOption, RequestPermissionResponse,
            AllowedOutcome, DeniedOutcome,
        )

        client = _CollectorClient(permission_policy='auto_approve')
        options = [
            PermissionOption(option_id='allow_once', name='Allow',
                             kind='allow_once'),
            PermissionOption(option_id='deny_once', name='Deny',
                             kind='reject_once'),
        ]
        tool_call = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            client.request_permission(options, 'ses_1', tool_call))

        assert isinstance(result, RequestPermissionResponse)
        assert isinstance(result.outcome, AllowedOutcome)
        assert result.outcome.outcome == 'selected'
        assert result.outcome.option_id == 'allow_once'

    def test_deny_returns_cancelled(self):
        from ms_agent.acp.client import _CollectorClient
        from acp.schema import (
            PermissionOption, RequestPermissionResponse, DeniedOutcome,
        )

        client = _CollectorClient(permission_policy='deny_all')
        options = [
            PermissionOption(option_id='allow_once', name='Allow',
                             kind='allow_once'),
        ]
        tool_call = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            client.request_permission(
                [o for o in options if 'deny' in o.kind],
                'ses_1', tool_call))

        assert isinstance(result, RequestPermissionResponse)
        assert isinstance(result.outcome, DeniedOutcome)


class TestFullMessageFlow:
    """Simulate a complete message flow and verify all updates are correct."""

    def test_full_agent_turn_with_tool_call(self):
        t = ACPTranslator()

        all_updates = []

        msgs = [Message(role='assistant', content='Let me ')]
        all_updates.extend(t.messages_to_updates(msgs))

        msgs[0] = Message(role='assistant', content='Let me search for that.')
        all_updates.extend(t.messages_to_updates(msgs))

        tc = {'id': 'tc_search', 'tool_name': 'web_search',
              'arguments': '{"query": "test topic"}'}
        msgs[0] = Message(
            role='assistant',
            content='Let me search for that.',
            tool_calls=[tc],
        )
        all_updates.extend(t.messages_to_updates(msgs))

        msgs.append(Message(
            role='tool', content='Found 3 results...',
            tool_call_id='tc_search', name='web_search',
        ))
        all_updates.extend(t.messages_to_updates(msgs))

        msg_chunks = [u for u in all_updates
                      if getattr(u, 'session_update', '') == 'agent_message_chunk']
        tool_starts = [u for u in all_updates
                       if getattr(u, 'session_update', '') == 'tool_call']
        tool_updates = [u for u in all_updates
                        if getattr(u, 'session_update', '') == 'tool_call_update']

        assert len(msg_chunks) >= 2, 'Should have streamed text incrementally'
        assert len(tool_starts) == 1, 'Should have exactly one tool_call start'
        assert len(tool_updates) == 1, 'Should have exactly one tool_call_update'
        assert tool_starts[0].kind == 'search'
        assert tool_updates[0].status == 'completed'

    def test_full_file_edit_flow(self):
        t = ACPTranslator()

        tc = {'id': 'tc_edit', 'tool_name': 'file_write',
              'arguments': json.dumps({
                  'path': '/project/src/app.py',
                  'content': 'def main():\n    print("hello")\n',
              })}

        msgs = [
            Message(role='assistant',
                    content='I will create the file for you.',
                    tool_calls=[tc]),
        ]
        u1 = t.messages_to_updates(msgs)

        msgs.append(Message(
            role='tool', content='Save file <src/app.py> successfully.',
            tool_call_id='tc_edit', name='file_write',
        ))
        u2 = t.messages_to_updates(msgs)

        tool_starts = [u for u in u1
                       if getattr(u, 'session_update', '') == 'tool_call']
        assert len(tool_starts) == 1
        assert tool_starts[0].kind == 'edit'
        assert 'Edit' in tool_starts[0].title

        tool_updates = [u for u in u2
                        if getattr(u, 'session_update', '') == 'tool_call_update']
        assert len(tool_updates) == 1
        assert tool_updates[0].status == 'completed'

        has_diff = any(
            getattr(c, 'type', '') == 'diff'
            for c in (tool_updates[0].content or []))
        assert has_diff, 'File write should produce diff content'


class TestErrorDetection:

    def test_error_markers(self):
        assert ACPTranslator._looks_like_error(
            'Error: file not found') is True
        assert ACPTranslator._looks_like_error(
            'Traceback (most recent call last)...') is True
        assert ACPTranslator._looks_like_error(
            '{"success": false, "error": "timeout"}') is True
        assert ACPTranslator._looks_like_error(
            'Operation failed due to timeout') is True

    def test_success_messages(self):
        assert ACPTranslator._looks_like_error(
            'Save file successfully.') is False
        assert ACPTranslator._looks_like_error(
            'Found 5 results about quantum computing') is False
        assert ACPTranslator._looks_like_error('') is False
        assert ACPTranslator._looks_like_error(
            '{"success": true, "output": "hello"}') is False


class TestResetTurn:

    def test_reset_clears_all_state(self):
        t = ACPTranslator()
        t._last_content_len = 100
        t._last_reasoning_len = 50
        t._emitted_tool_ids.add('tc_1')
        t._completed_tool_ids.add('tc_1')
        t._tool_args_cache['tc_1'] = {'path': '/test'}
        t._tool_name_cache['tc_1'] = 'file_write'
        t._last_seen_msg_count = 5

        t.reset_turn()

        assert t._last_content_len == 0
        assert t._last_reasoning_len == 0
        assert len(t._emitted_tool_ids) == 0
        assert len(t._completed_tool_ids) == 0
        assert len(t._tool_args_cache) == 0
        assert len(t._tool_name_cache) == 0
        assert t._last_seen_msg_count == 0


class TestPromptToMessages:

    def test_resource_block(self):
        block = MagicMock()
        block.type = 'resource'
        block.resource = MagicMock()
        block.resource.text = 'file contents here'
        block.resource.uri = 'file:///src/main.py'
        msgs = ACPTranslator.prompt_to_messages([block])
        assert 'file:///src/main.py' in msgs[0].content
        assert 'file contents here' in msgs[0].content

    def test_resource_link_block(self):
        block = MagicMock()
        block.type = 'resource_link'
        block.uri = 'file:///README.md'
        msgs = ACPTranslator.prompt_to_messages([block])
        assert 'file:///README.md' in msgs[0].content

    def test_image_block(self):
        block = MagicMock()
        block.type = 'image'
        msgs = ACPTranslator.prompt_to_messages([block])
        assert 'Image' in msgs[0].content
