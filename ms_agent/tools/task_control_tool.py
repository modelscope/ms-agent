# Copyright (c) ModelScope Contributors. All rights reserved.
import json
from typing import Any, Dict, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils.logger import get_logger
from omegaconf import DictConfig

logger = get_logger()

_SERVER = 'task_control'


class TaskControlTool(ToolBase):
    """Exposes background task management to the LLM.

    Provides two tools:
    - list_tasks: show all background tasks and their status
    - cancel_task: kill a running background task by task_id
    """

    def __init__(self, config: DictConfig, **kwargs):
        super().__init__(config)
        self._task_manager = None

    def set_task_manager(self, task_manager) -> None:
        self._task_manager = task_manager

    async def connect(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        return {
            _SERVER: [
                Tool(
                    tool_name='list_tasks',
                    server_name=_SERVER,
                    description=(
                        'List all background tasks and their current status. '
                        'Returns task_id, tool_name, description, status, and duration.'),
                    parameters={
                        'type': 'object',
                        'properties': {},
                        'required': [],
                        'additionalProperties': False,
                    },
                ),
                Tool(
                    tool_name='cancel_task',
                    server_name=_SERVER,
                    description='Cancel a running background task by its task_id.',
                    parameters={
                        'type': 'object',
                        'properties': {
                            'task_id': {
                                'type': 'string',
                                'description': 'The task_id returned by the async_launched response.',
                            }
                        },
                        'required': ['task_id'],
                        'additionalProperties': False,
                    },
                ),
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if self._task_manager is None:
            return 'TaskManager not available.'

        if tool_name == 'list_tasks':
            tasks = list(self._task_manager._tasks.values())
            if not tasks:
                return 'No background tasks registered.'
            rows = []
            for t in tasks:
                duration = ''
                if t.ended_at:
                    duration = f'{t.ended_at - t.started_at:.1f}s'
                elif t.status == 'running':
                    import time
                    duration = f'{time.monotonic() - t.started_at:.1f}s (running)'
                rows.append({
                    'task_id': t.task_id,
                    'tool_name': t.tool_name,
                    'description': t.description,
                    'status': t.status,
                    'duration': duration,
                })
            return json.dumps(rows, ensure_ascii=False, indent=2)

        if tool_name == 'cancel_task':
            task_id = tool_args.get('task_id', '')
            task = self._task_manager.get_task(task_id)
            if task is None:
                return f'Task "{task_id}" not found.'
            if task.status != 'running':
                return f'Task "{task_id}" is already {task.status}.'
            self._task_manager.kill(task_id)
            return f'Task "{task_id}" cancelled.'

        return f'Unknown tool: {tool_name}'
