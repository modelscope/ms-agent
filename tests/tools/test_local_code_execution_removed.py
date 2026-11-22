"""Removed local execution tools cannot be revived by legacy configuration."""

import json
import os
import shlex
import sys
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.tools.code.local_code_executor import LocalCodeExecutionTool
from ms_agent.tools.tool_manager import ToolManager

REMOVED_TOOLS = (
    'python_executor',
    'notebook_executor',
    'reset_executor',
    'get_executor_info',
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def local_config(workspace, **scope):
    return OmegaConf.create({
        'output_dir': str(workspace),
        'tools': {
            'code_executor': {
                'mcp': False,
                'implementation': 'python_env',
                **scope,
            },
        },
    })


@pytest.mark.asyncio
@pytest.mark.parametrize('scope, expected', [
    ({}, {'shell_executor', 'file_operation'}),
    ({'include': ['shell_executor', *REMOVED_TOOLS]}, {'shell_executor'}),
    ({'include': list(REMOVED_TOOLS)}, set()),
    ({'exclude': list(REMOVED_TOOLS)}, {'shell_executor', 'file_operation'}),
])
async def test_removed_tools_are_not_registered(tmp_path, scope, expected):
    tool = LocalCodeExecutionTool(local_config(tmp_path, **scope))
    try:
        tools = await tool.get_tools()
        assert {item['tool_name'] for item in tools['code_executor']} == expected
    finally:
        await tool.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('name', REMOVED_TOOLS)
async def test_removed_tools_reject_direct_dispatch(tmp_path, name):
    marker = tmp_path / 'must-not-exist.txt'
    code = f'open({str(marker)!r}, "w").write("unexpected execution")'
    tool = LocalCodeExecutionTool(local_config(tmp_path, include=[name]))
    try:
        result = json.loads(await tool.call_tool(
            'code_executor', tool_name=name, tool_args={'code': code}))
        assert result['success'] is False
        assert result['error'] == f'Unknown tool: {name}'
        assert not hasattr(tool, name)
        assert not marker.exists()
    finally:
        await tool.cleanup()


@pytest.mark.asyncio
async def test_tool_manager_rejects_removed_tools_with_legacy_config(tmp_path):
    manager = ToolManager(local_config(
        tmp_path, include=['shell_executor', *REMOVED_TOOLS]))
    marker = tmp_path / 'must-not-exist.txt'
    try:
        await manager.connect()
        for name in REMOVED_TOOLS:
            result = await manager.single_call_tool({
                'tool_name': f'code_executor---{name}',
                'arguments': {
                    'code': f'open({str(marker)!r}, "w").write("unexpected")',
                },
            })
            assert result['is_error'] is True
            assert 'is not available' in result['result']
        assert not marker.exists()
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == 'nt', reason='POSIX command quoting')
async def test_shell_results_enter_conversation_without_files(tmp_path):
    manager = ToolManager(local_config(tmp_path, include=['shell_executor']))
    agent = LLMAgent.__new__(LLMAgent)
    agent.tool_manager = manager
    agent._event_sink = None
    agent.log_output = lambda content: None
    messages = []

    async def run_code(code, call_id):
        messages.append(Message(role='assistant', tool_calls=[{
            'id': call_id,
            'tool_name': 'code_executor---shell_executor',
            'arguments': {
                'command': f'{shlex.quote(sys.executable)} -c {shlex.quote(code)}',
            },
        }]))
        await agent.parallel_tool_call(messages)
        message = messages[-1]
        assert message.role == 'tool'
        assert message.tool_call_id == call_id
        result = json.loads(message.content)
        assert result['success'] is True, result
        assert result['truncated'] is False
        return result['output']

    try:
        await manager.connect()
        observed = await run_code('total = sum([1, 2, 3]); print(total)', 'sum')
        assert observed == '6'
        # Later code can use a value returned in the conversation, while the
        # preceding process's Python variables do not survive.
        doubled = await run_code(
            f'assert "total" not in globals(); print({int(observed)} * 2)',
            'double')
        assert doubled == '12'
        assert [m.tool_call_id for m in messages if m.role == 'tool'] == [
            'sum', 'double'
        ]
        assert not list(tmp_path.iterdir())
    finally:
        await manager.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize('filename', [
    'skill_evolution/agents/macro_skill_manager.yaml',
    'skill_evolution/agents/micro_skill_manager.yaml',
    'skill_evolution/agents/rollout.yaml',
])
async def test_existing_local_file_operations_remain_available(tmp_path, filename):
    config = OmegaConf.load(REPO_ROOT / 'projects' / filename)
    config.output_dir = str(tmp_path)
    tool = LocalCodeExecutionTool(config)
    try:
        tools = await tool.get_tools()
        assert {item['tool_name'] for item in tools['code_executor']} == {
            'shell_executor', 'file_operation'
        }
        result = json.loads(await tool.call_tool(
            'code_executor', tool_name='file_operation', tool_args={
                'operation': 'write',
                'file_path': 'kept.txt',
                'content': 'existing capability',
            }))
        assert result['success'] is True, result
        assert (tmp_path / 'kept.txt').read_text() == 'existing capability'
    finally:
        await tool.cleanup()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == 'nt', reason='POSIX command quoting')
@pytest.mark.parametrize('filename', [
    'researcher.yaml',
    'researcher.tavily.yaml',
    'researcher.exp_nosnap.yaml',
])
async def test_researcher_can_write_and_run_analysis_script(tmp_path, filename):
    researcher = OmegaConf.load(
        REPO_ROOT / 'projects' / 'deep_research' / 'v2' / filename)
    manager = ToolManager(OmegaConf.create({
        'output_dir': str(tmp_path),
        'tools': {
            'file_system': researcher.tools.file_system,
            'code_executor': researcher.tools.code_executor,
        },
    }))
    script = (
        'import json, os\n'
        'from pathlib import Path\n'
        'result = {"total": sum([1, 2, 3]), "pid": os.getpid()}\n'
        'Path("analysis.json").write_text(json.dumps(result))\n'
        'print("analysis complete")\n'
    )
    try:
        await manager.connect()
        tools = {tool['tool_name']: tool for tool in await manager.get_tools()}
        shell = tools['code_executor---shell_executor']
        assert shell['parameters']['properties']['timeout']['default'] == 120
        assert not any(f'code_executor---{name}' in tools for name in REMOVED_TOOLS)

        await manager.single_call_tool({
            'tool_name': 'file_system---write_file',
            'arguments': {'path': 'analysis.py', 'content': script},
        })
        result = json.loads(await manager.single_call_tool({
            'tool_name': 'code_executor---shell_executor',
            'arguments': {
                'command': f'{shlex.quote(sys.executable)} analysis.py',
            },
        }))
        assert result['success'] is True, result
        assert result['output'] == 'analysis complete'
        saved = json.loads((tmp_path / 'analysis.json').read_text())
        assert saved['total'] == 6
        assert saved['pid'] != os.getpid()
    finally:
        await manager.cleanup()
