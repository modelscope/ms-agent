# Copyright (c) Alibaba, Inc. and its affiliates.
"""TodoGateCallback -- don't let the agent stop with unfinished plan items.

When the agent decides to stop (``runtime.should_stop`` is True) but the
todo_list plan (``plan.json``) still has incomplete items, inject a reminder and
keep going, bounded by ``max_reminders``. Generalized from deer-flow's
TodoMiddleware premature-exit guard. If there is no plan file, it never blocks.
"""
from __future__ import annotations

import json
import os
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()

_DONE = {'completed', 'cancelled'}


class TodoGateCallback(Callback):
    """Config block::

        todo_gate:
          enabled: true
          max_reminders: 2
          plan_file: plan.json    # relative to output_dir (or absolute)
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'todo_gate', None)
        self.enabled = bool(getattr(cfg, 'enabled', True))
        self.max_reminders = int(getattr(cfg, 'max_reminders', 2))
        self.plan_file = str(getattr(cfg, 'plan_file', 'plan.json'))
        self.output_dir = getattr(config, 'output_dir', None) or '.'
        self._used = 0

    def _plan_path(self) -> str:
        return self.plan_file if os.path.isabs(self.plan_file) else os.path.join(
            self.output_dir, self.plan_file)

    def _incomplete(self) -> list:
        path = self._plan_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return []
        if isinstance(data, dict):
            todos = data.get('todos') or []
        elif isinstance(data, list):
            todos = data
        else:
            todos = []
        return [
            t for t in todos
            if str((t or {}).get('status', '')).strip().lower() not in _DONE
        ]

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled or not runtime.should_stop:
            return
        if self._used >= self.max_reminders:
            return
        incomplete = self._incomplete()
        if not incomplete:
            return
        sample = ', '.join(
            str((t or {}).get('content', ''))[:40] for t in incomplete[:5])
        messages.append(
            Message(
                role='user',
                content=(
                    f'[TODO_GATE] {len(incomplete)} planned item(s) are not yet '
                    f'completed (e.g. {sample}). Continue and finish them, or '
                    'explicitly explain why they cannot be completed, before '
                    'stopping.')))
        runtime.should_stop = False
        self._used += 1
        logger.info('TodoGate: blocked stop, %d incomplete (%d/%d)',
                    len(incomplete), self._used, self.max_reminders)
