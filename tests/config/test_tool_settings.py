import asyncio
import json

import pytest
from omegaconf import OmegaConf

from ms_agent.config.resolver import ConfigResolver
from ms_agent.config.tool_settings import merge_tool_settings
from ms_agent.tools.tool_manager import ToolManager


def test_interface_defaults_are_below_user_layers(tmp_path):
    defaults = {'tools': {
        'todo_list': {'mcp': False},
        'code_executor': {'mcp': False, 'implementation': 'python_env',
                          'include': ['shell_executor']},
    }}
    original = json.dumps(defaults)
    (tmp_path / 'settings.json').write_text(json.dumps({'tools': {
        'code_executor': {'enabled': False},
        'todo_list': {'auto_render_md': False},
    }}))
    project = tmp_path / 'project'
    (project / '.ms_agent').mkdir(parents=True)
    (project / '.ms_agent' / 'config.yaml').write_text(
        'tools:\n  code_executor:\n    exclude: [shell_executor]\n')
    cfg = ConfigResolver(global_dir=tmp_path, defaults=defaults).resolve(
        project_path=str(project),
        session_overrides={'tools': {'todo_list': {'plan_filename': 'session.json'}}})
    assert cfg.tools.todo_list.mcp is False
    assert cfg.tools.todo_list.auto_render_md is False
    assert cfg.tools.todo_list.plan_filename == 'session.json'
    assert cfg.tools.code_executor.enabled is False
    assert 'include' not in cfg.tools.code_executor
    assert list(cfg.tools.code_executor.exclude) == ['shell_executor']
    assert json.dumps(defaults) == original
    # An interface's defaults never leak into a normal SDK resolver.
    plain = ConfigResolver(global_dir=tmp_path / 'other').resolve()
    assert 'todo_list' not in plain.tools
    assert list(plain.tools.code_executor.include) == ['shell_executor']


@pytest.mark.parametrize('patch', [None, [], {'todo_list': None},
                                 {'todo_list': False}, {'todo_list': {'mcp': 'false'}},
                                 {'todo_list': {'enabled': 'false'}},
                                 {'file_system': {'include': 'read_file'}},
                                 {'file_system': {'include': ['a'], 'exclude': ['b']}}])
def test_invalid_tool_config_has_actionable_error(patch):
    with pytest.raises(ValueError, match='tools'):
        merge_tool_settings({}, patch)


@pytest.mark.parametrize('selection,removed', [('include', 'exclude'), ('exclude', 'include')])
def test_selection_replaces_inherited_mode_even_if_empty(selection, removed):
    base = {'file_system': {'mcp': False, removed: ['write_file'], 'enabled': False}}
    merged = merge_tool_settings(base, {'file_system': {selection: []}})
    assert removed not in merged['file_system']
    assert merged['file_system'][selection] == []
    assert merged['file_system']['enabled'] is False
    assert removed in base['file_system']


def test_partial_config_cannot_change_builtin_tool_to_mcp():
    with pytest.raises(ValueError, match='built-in tool'):
        merge_tool_settings({'todo_list': {'mcp': False}}, {'todo_list': {'mcp': True}})


def test_disabled_code_executor_does_not_register_or_connect(tmp_path):
    async def check():
        manager = ToolManager(OmegaConf.create({
            'output_dir': str(tmp_path),
            'tools': {'code_executor': {'mcp': False, 'enabled': False,
                                        'implementation': 'python_env'}},
        }))
        try:
            await manager.connect()
            assert not manager.extra_tools
            assert not await manager.get_tools()
        finally:
            await manager.cleanup()
    asyncio.run(check())
