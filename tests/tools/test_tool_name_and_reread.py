"""Two ways a tool call used to dead-end: an unusable name error, and a read
that returned no content."""
import json
import os

import pytest
from omegaconf import OmegaConf

from ms_agent.tools.tool_manager import ToolManager


def _fs_config(workspace):
    return OmegaConf.create({
        'output_dir': str(workspace),
        'tools': {'file_system': {}},
    })


def _manager_with(index_keys) -> ToolManager:
    manager = ToolManager.__new__(ToolManager)
    manager._tool_index = {key: (None, 'srv', {}) for key in index_keys}
    return manager


def test_unambiguous_shorthand_resolves_and_says_so():
    manager = _manager_with(['code_executor---shell_executor'])
    resolved, note = manager._resolve_tool_name('code_executor')
    assert resolved == 'code_executor---shell_executor'
    assert 'exact tool name' in note


def test_ambiguous_shorthand_is_not_guessed():
    manager = _manager_with(
        ['code_executor---shell_executor', 'code_executor---file_operation'])
    resolved, _ = manager._resolve_tool_name('code_executor')
    assert resolved is None


def test_unknown_name_reports_candidates_not_a_traceback():
    manager = _manager_with(
        ['file_system---read_file', 'file_system---write_file'])
    message = manager._unknown_tool_message('file_system---raed_file')
    assert 'file_system---read_file' in message
    assert 'exact tool name' in message
    assert 'AssertionError' not in message
    assert 'Traceback' not in message


@pytest.mark.asyncio
async def test_reading_the_same_file_twice_returns_content_both_times(tmp_path):
    """A second read must never come back empty-handed: after a context
    truncation the first read is gone, and withholding content on the grounds
    that it "has not changed" leaves the model with no way to obtain the file.
    """
    from ms_agent.tools.filesystem_tool import FileSystemTool

    workspace = tmp_path / 'ws'
    workspace.mkdir()
    (workspace / 'rules.md').write_text('v1 rules\n', encoding='utf-8')

    tool = FileSystemTool(_fs_config(workspace))

    first = await tool.call_tool(
        'file_system', tool_name='read_file', tool_args={'path': 'rules.md'})
    second = await tool.call_tool(
        'file_system', tool_name='read_file', tool_args={'path': 'rules.md'})

    first_payload = json.loads(first)['rules.md']
    second_payload = json.loads(second)['rules.md']

    assert 'v1 rules' in first_payload
    assert 'v1 rules' in second_payload, 'content withheld on re-read'
    assert 'unchanged since your last read' in second_payload


@pytest.mark.asyncio
async def test_rereading_after_a_change_reports_the_new_content(tmp_path):
    from ms_agent.tools.filesystem_tool import FileSystemTool

    workspace = tmp_path / 'ws'
    workspace.mkdir()
    target = workspace / 'rules.md'
    target.write_text('v1\n', encoding='utf-8')

    tool = FileSystemTool(_fs_config(workspace))
    await tool.call_tool(
        'file_system', tool_name='read_file', tool_args={'path': 'rules.md'})

    # Push mtime forward so the change is visible whatever the clock's
    # granularity is.
    target.write_text('v2\n', encoding='utf-8')
    future = os.path.getmtime(target) + 2
    os.utime(target, (future, future))

    again = await tool.call_tool(
        'file_system', tool_name='read_file', tool_args={'path': 'rules.md'})
    payload = json.loads(again)['rules.md']
    assert 'v2' in payload
    assert 'unchanged' not in payload
