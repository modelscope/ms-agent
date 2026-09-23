"""TodoListTool lock-dir placement: canonical internal dir by default."""
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


def test_absolute_plan_filename_is_not_joined_under_output_dir(tmp_path):
    sess = tmp_path / 'sessions' / 'abc'
    sess.mkdir(parents=True)
    plan_json = str(sess / 'plan.json')
    plan_md = str(sess / 'plan.md')
    tool = _make(tmp_path, plan_filename=plan_json, plan_md_filename=plan_md)
    paths = tool._paths()
    assert paths.plan_json == plan_json
    assert paths.plan_md == plan_md
