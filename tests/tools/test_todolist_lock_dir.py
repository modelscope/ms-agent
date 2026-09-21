"""TodoListTool lock-dir placement: canonical internal dir by default."""
import json
import os

import pytest

from ms_agent.tools.todolist_tool import TodoListTool


class _Cfg:
    """Minimal config shim: config.tools.todo_list.<fields> + output_dir."""

    def __init__(self, tmp_path, **tool_fields):
        class _Tool:
            pass

        tool = _Tool()
        for k, v in tool_fields.items():
            setattr(tool, k, v)

        class _Tools:
            todo_list = tool

        self.tools = _Tools()
        self.output_dir = str(tmp_path)


def _make(tmp_path, **tool_fields) -> TodoListTool:
    tool = TodoListTool(_Cfg(tmp_path, **tool_fields))
    tool.output_dir = str(tmp_path)
    return tool


def test_lock_dir_defaults_to_internal_ms_agent_locks(tmp_path):
    # No explicit lock_subdir -> canonical <output_dir>/.ms_agent/locks, so the
    # workspace root is never littered with a ".locks" dir.
    tool = _make(tmp_path)
    assert tool._lock_dir() == str(tmp_path / '.ms_agent' / 'locks')


@pytest.mark.asyncio
async def test_connect_creates_internal_lock_dir_not_workspace_dot_locks(tmp_path):
    tool = _make(tmp_path)
    await tool.connect()
    assert (tmp_path / '.ms_agent' / 'locks').is_dir()
    assert not (tmp_path / '.locks').exists()


def test_explicit_lock_subdir_still_wins(tmp_path):
    tool = _make(tmp_path, lock_subdir='.mylocks')
    assert tool._lock_dir() == os.path.join(str(tmp_path), '.mylocks')


@pytest.mark.asyncio
@pytest.mark.parametrize('auto_render', [True, False])
async def test_session_plan_locations_match_tool_contract(tmp_path, auto_render):
    session = tmp_path / 'sessions' / 'child'
    session.mkdir(parents=True)
    original = tmp_path / 'plan.json'
    original.write_text('{"todos": []}')
    tool = _make(
        tmp_path, plan_filename=str(session / 'plan.json'),
        plan_md_filename=str(session / 'plan.md'), auto_render_md=auto_render)
    schemas = {t['tool_name']: t for t in (await tool.get_tools())['todo_list']}
    for schema in schemas.values():
        assert str(session / 'plan.json') in schema['description']
    path_help = schemas['todo_render_md']['parameters']['properties']['path']['description']
    assert str(session / 'plan.md') in path_help
    assert ('automatically' in schemas['todo_write']['description']) == auto_render

    await tool.todo_write([{'id': 'A', 'content': 'Child task', 'status': 'pending'}])
    assert json.loads(await tool.todo_read())[0]['content'] == 'Child task'
    assert (session / 'plan.md').exists() == auto_render
    await tool.todo_render_md()
    assert 'Child task' in (session / 'plan.md').read_text()
    assert original.read_text() == '{"todos": []}'
