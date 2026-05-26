"""CronTool: agent-facing tool for managing cron jobs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from ms_agent.cron.executor import is_in_cron_context
from ms_agent.cron.manager import JobManager
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


class CronTool(ToolBase):
    """Cron job management tool for ms-agent.

    The tool name visible to the LLM is 'cron---cron'.
    """

    SERVER_NAME = 'cron'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        if hasattr(config, 'tools') and hasattr(config.tools, 'cron'):
            self.exclude_func(config.tools.cron)
        workspace = os.environ.get(
            'MS_AGENT_CRON_WORKSPACE',
            os.path.expanduser('~/.ms_agent/cron'),
        )
        self._manager = JobManager(Path(workspace))

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, List[Tool]]:
        return {
            self.SERVER_NAME: [
                Tool(
                    tool_name='cron',
                    server_name=self.SERVER_NAME,
                    description=(
                        'Manage cron (scheduled) tasks. '
                        'Actions: create, list, pause, resume, run, remove, history.'
                    ),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'action': {
                                'type': 'string',
                                'enum': ['create', 'list', 'pause', 'resume', 'run', 'remove', 'history'],
                                'description': 'The action to perform.',
                            },
                            'schedule': {
                                'type': 'string',
                                'description': (
                                    'Schedule expression (required for create). '
                                    'Examples: "0 9 * * *", "every 30m", "2025-06-01T09:00:00"'
                                ),
                            },
                            'prompt': {
                                'type': 'string',
                                'description': 'Task prompt (required for create).',
                            },
                            'name': {
                                'type': 'string',
                                'description': 'Human-readable task name.',
                            },
                            'job_id': {
                                'type': 'string',
                                'description': 'Job ID (required for non-create actions).',
                            },
                        },
                        'required': ['action'],
                    },
                )
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str, tool_args: dict) -> str:
        if is_in_cron_context():
            return _json_dumps({'error': 'Cannot manage cron jobs from within a cron job execution.'})

        action = tool_args.get('action', '')
        handler = getattr(self, f'_action_{action}', None)
        if handler is None:
            return _json_dumps({'error': f'Unknown action: {action}'})
        return await handler(tool_args)

    async def _action_create(self, args: dict) -> str:
        schedule = args.get('schedule')
        prompt = args.get('prompt')
        if not schedule or not prompt:
            return _json_dumps({'error': 'Both "schedule" and "prompt" are required for create.'})
        try:
            job = self._manager.create_job(
                schedule_str=schedule,
                prompt=prompt,
                name=args.get('name', ''),
            )
            return _json_dumps({
                'status': 'created',
                'job_id': job.id,
                'name': job.name,
                'schedule': job.schedule.to_dict(),
            })
        except Exception as e:
            return _json_dumps({'error': str(e)})

    async def _action_list(self, args: dict) -> str:
        jobs = self._manager.list_jobs(include_disabled=True)
        result = []
        for job, state in jobs:
            result.append({
                'id': job.id,
                'name': job.name,
                'enabled': job.enabled,
                'schedule': job.schedule.to_dict(),
                'status': state.status,
                'next_run_at': state.next_run_at,
                'last_run_at': state.last_run_at,
                'run_count': state.run_count,
            })
        return _json_dumps(result)

    async def _action_pause(self, args: dict) -> str:
        job_id = args.get('job_id')
        if not job_id:
            return _json_dumps({'error': '"job_id" is required.'})
        ok = self._manager.pause_job(job_id)
        return _json_dumps({'status': 'paused' if ok else 'failed', 'job_id': job_id})

    async def _action_resume(self, args: dict) -> str:
        job_id = args.get('job_id')
        if not job_id:
            return _json_dumps({'error': '"job_id" is required.'})
        ok = self._manager.resume_job(job_id)
        return _json_dumps({'status': 'resumed' if ok else 'failed', 'job_id': job_id})

    async def _action_run(self, args: dict) -> str:
        job_id = args.get('job_id')
        if not job_id:
            return _json_dumps({'error': '"job_id" is required.'})
        ok = self._manager.trigger_job(job_id)
        return _json_dumps({'status': 'triggered' if ok else 'failed', 'job_id': job_id})

    async def _action_remove(self, args: dict) -> str:
        job_id = args.get('job_id')
        if not job_id:
            return _json_dumps({'error': '"job_id" is required.'})
        ok = self._manager.delete_job(job_id)
        return _json_dumps({'status': 'removed' if ok else 'not_found', 'job_id': job_id})

    async def _action_history(self, args: dict) -> str:
        job_id = args.get('job_id')
        if not job_id:
            return _json_dumps({'error': '"job_id" is required.'})
        records = self._manager.get_history(job_id)
        return _json_dumps([r.to_dict() for r in records])
