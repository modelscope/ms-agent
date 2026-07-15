# Copyright (c) ModelScope Contributors. All rights reserved.
"""ScheduleWakeupTool: self-pacing primitive for the in-session ``/loop``.

During a self-paced (or maintenance) loop, the model ends each iteration by
calling ``schedule_wakeup(delay_seconds, reason)`` to choose when to wake next.
NOT calling it during an iteration ends the loop cleanly -- that is the intended
"the task is done" signal (mirrors Claude Code's ScheduleWakeup semantics).

The decision is recorded on the shared :class:`LoopController` (injected via
``set_loop_controller`` in ``LLMAgent.prepare_tools``), which reads it after the
turn ends to schedule the next iteration.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


class ScheduleWakeupTool(ToolBase):
    """Agent-facing tool to schedule the next self-paced loop iteration.

    The tool name visible to the LLM is 'loop---schedule_wakeup'.
    """

    SERVER_NAME = 'loop'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'schedule_wakeup'):
            self.exclude_func(config.tools.schedule_wakeup)
        self._controller: Optional[Any] = None

    def set_loop_controller(self, controller) -> None:
        self._controller = controller

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, List[Tool]]:
        return {
            self.SERVER_NAME: [
                Tool(
                    tool_name='schedule_wakeup',
                    server_name=self.SERVER_NAME,
                    description=(
                        'Schedule the next iteration of the current self-paced '
                        '/loop. Call this at the END of a turn to wake again in '
                        '`delay_seconds` seconds (clamped to 60..3600). If the '
                        'task is verifiably complete, DO NOT call this -- the '
                        'loop then ends cleanly. Only meaningful inside a '
                        'self-paced /loop.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'delay_seconds': {
                                'type':
                                'integer',
                                'description':
                                ('Seconds to wait before the next iteration '
                                 '(60..3600). Short when work is imminent, '
                                 'long when idle.'),
                            },
                            'reason': {
                                'type':
                                'string',
                                'description':
                                ('Brief reason for the chosen delay (shown to '
                                 'the user).'),
                            },
                        },
                        'required': ['delay_seconds'],
                    },
                )
            ]
        }

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        if self._controller is None:
            return _json_dumps({
                'error':
                'schedule_wakeup is only available inside a self-paced /loop.'
            })
        delay = tool_args.get('delay_seconds')
        reason = tool_args.get('reason', '') or ''
        if delay is None:
            return _json_dumps({'error': '"delay_seconds" is required.'})
        clamped = self._controller.request_wakeup(delay, reason)
        return _json_dumps({
            'status': 'scheduled',
            'delay_seconds': clamped,
            'reason': reason,
        })
