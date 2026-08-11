# Copyright (c) ModelScope Contributors. All rights reserved.
"""LLMAgent._extract_plan_from_tool_result → PlanUpdated entries (todo panel)."""
from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message


def _tool(name, content):
    return Message(role='tool', name=name, content=content)


def test_todo_write_result_becomes_entries():
    m = _tool('todo_write',
              '{"todos": [{"content": "step 1", "status": "in_progress"},'
              ' {"content": "step 2"}]}')
    entries = LLMAgent._extract_plan_from_tool_result(m)
    assert len(entries) == 2
    assert entries[0].content == 'step 1' and entries[0].status == 'in_progress'
    assert entries[1].content == 'step 2' and entries[1].status == 'pending'


def test_server_prefixed_todo_name_matches():
    m = _tool('todolist---todo_read', '[{"task": "a", "status": "completed"}]')
    entries = LLMAgent._extract_plan_from_tool_result(m)
    assert len(entries) == 1 and entries[0].content == 'a'


def test_split_task_matches():
    assert LLMAgent._extract_plan_from_tool_result(
        _tool('split_task', '{"todos": [{"content": "x"}]}')) is not None


def test_non_todo_tool_ignored():
    assert LLMAgent._extract_plan_from_tool_result(
        _tool('file_system---read_file', 'contents')) is None


def test_malformed_json_ignored():
    assert LLMAgent._extract_plan_from_tool_result(
        _tool('todo_write', 'not json')) is None


def test_empty_todos_returns_none():
    assert LLMAgent._extract_plan_from_tool_result(
        _tool('todo_write', '{"todos": []}')) is None
