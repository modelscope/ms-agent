# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shell-only lifecycle and actual foreground/background interpreter selection."""
import asyncio
import json
import os
import shlex
import sys
import venv

import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent  # noqa: F401 — tools import cycle
from ms_agent.tools.code.local_code_executor import LocalCodeExecutionTool
from ms_agent.utils.task_manager import TaskManager


def config(root, **scope):
    return OmegaConf.create({'output_dir': str(root), 'tools': {'code_executor': scope}})


@pytest.mark.parametrize('scope', [
    {},
    {'include': ['shell_executor']},
    {'exclude': ['notebook_executor', 'python_executor', 'reset_executor']},
])
def test_local_lifecycle_does_not_install_dependencies(tmp_path, monkeypatch, scope):
    def unexpected(*args, **kwargs):
        pytest.fail('Local tool initialization must not install task dependencies')
    monkeypatch.setattr('ms_agent.utils.utils.install_package', unexpected)

    async def run():
        tool = LocalCodeExecutionTool(config(tmp_path, **scope))
        await tool.connect()
        await tool.connect()
        try:
            result = json.loads(await tool.shell_executor('echo shell-ready'))
            assert result['success'] and 'shell-ready' in result['output']
        finally:
            await tool.cleanup()
            await tool.cleanup()
    asyncio.run(run())


@pytest.mark.skipif(os.name == 'nt', reason='POSIX command quoting')
def test_real_shell_and_background_use_selected_python(tmp_path, monkeypatch):
    project_env = tmp_path / 'task-env'
    venv.EnvBuilder(with_pip=True).create(project_env)
    monkeypatch.setenv('MS_AGENT_SHELL_PATH', str(project_env / 'bin') + os.pathsep + os.defpath)
    parent_path = os.environ.get('PATH')
    expected = str(project_env)
    command = 'python -c ' + shlex.quote('import sys; print(sys.prefix)')

    async def run():
        tool = LocalCodeExecutionTool(config(tmp_path / 'workspace', include=['shell_executor']))
        tasks = TaskManager()
        tool.set_task_manager(tasks)
        await tool.connect()
        try:
            tools = await tool.get_tools()
            description = tools['code_executor'][0]['description']
            assert str(project_env / 'bin/python') in description
            assert str(project_env / 'bin/pip') in description
            assert sys.executable in description
            result = json.loads(await tool.shell_executor(command))
            assert result['success'] and result['output'].strip() == expected
            started = json.loads(await tool.shell_executor(command, run_in_background=True))
            task = tasks.get_task(started['task_id'])
            await asyncio.wait_for(asyncio.gather(*tool._watcher_tasks), timeout=30)
            assert task.status == 'completed'
            assert json.loads(task.result)['output'].strip() == expected
        finally:
            await tool.cleanup()
    asyncio.run(run())
    assert sys.prefix != expected
    assert os.environ.get('PATH') == parent_path
