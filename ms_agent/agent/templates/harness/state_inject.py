# Copyright (c) Alibaba, Inc. and its affiliates.
"""StateInjectCallback -- fill environment placeholders in the system prompt.

At task start, replaces ``<current_date>`` / ``<cwd>`` / ``<os>`` in the system
message with live values. Done once (task_begin) so the prompt stays stable for
the rest of the run (KV-cache friendly). Volatile per-round state (round count)
is intentionally NOT injected here -- that rides in user messages via
``RoundReminderCallback``.
"""
from __future__ import annotations

import datetime
import os
import platform
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()


class StateInjectCallback(Callback):
    """Substitute environment placeholders in the system prompt at task start.

    Config block (all optional)::

        state_inject:
          enabled: true
          fields: [date, cwd, os]   # which placeholders to fill
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'state_inject', None)
        self.enabled = bool(getattr(cfg, 'enabled', True))
        fields = getattr(cfg, 'fields', None)
        self.fields = set(fields) if fields else {'date', 'cwd', 'os'}

    def _values(self) -> dict:
        vals = {}
        if 'date' in self.fields:
            vals['<current_date>'] = datetime.datetime.now().strftime(
                '%Y-%m-%d')
        if 'cwd' in self.fields:
            vals['<cwd>'] = os.getcwd()
        if 'os' in self.fields:
            vals['<os>'] = platform.platform()
        return vals

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled or not messages:
            return
        msg = messages[0]
        if msg.role != 'system' or not isinstance(msg.content, str):
            return
        content = msg.content
        for placeholder, value in self._values().items():
            if placeholder in content:
                content = content.replace(placeholder, value)
        msg.content = content
