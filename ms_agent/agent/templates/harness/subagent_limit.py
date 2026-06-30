# Copyright (c) Alibaba, Inc. and its affiliates.
"""SubagentLimitCallback -- hard cap on parallel sub-agent delegations per turn.

If a single assistant response issues more than ``max_parallel`` delegation
(``agent_tools---*``) calls, the excess are dropped before execution (kept calls
still get their tool results, so nothing dangles). Generalized from deer-flow's
SubagentLimitMiddleware.

Truncation happens in ``on_tool_call`` (before the tools run); the explanatory
*user* message is emitted in ``after_tool_call`` (injecting it before the tool
results would be malformed).
"""
from __future__ import annotations

from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()

_DELEGATION_PREFIX = 'agent_tools---'


class SubagentLimitCallback(Callback):
    """Config block::

        subagent_limit:
          enabled: true
          max_parallel: 4
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'subagent_limit', None)
        self.enabled = bool(getattr(cfg, 'enabled', True))
        self.max_parallel = int(getattr(cfg, 'max_parallel', 4))
        self._pending_dropped = 0

    @staticmethod
    def _name(tc) -> str:
        return str(tc.get('tool_name', '') if isinstance(tc, dict) else getattr(
            tc, 'tool_name', ''))

    def _is_delegation(self, tc) -> bool:
        return self._name(tc).startswith(_DELEGATION_PREFIX)

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled or not messages:
            return
        m = messages[-1]
        if m.role != 'assistant' or not m.tool_calls:
            return
        kept, dropped, seen = [], 0, 0
        for tc in m.tool_calls:
            if self._is_delegation(tc):
                seen += 1
                if seen > self.max_parallel:
                    dropped += 1
                    continue
            kept.append(tc)
        if dropped:
            m.tool_calls = kept
            self._pending_dropped = dropped
            logger.warning(
                'SubagentLimit: dropped %d excess delegation call(s) (max %d)',
                dropped, self.max_parallel)

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self._pending_dropped:
            return
        dropped, self._pending_dropped = self._pending_dropped, 0
        messages.append(
            Message(
                role='user',
                content=(
                    f'[SUBAGENT_LIMIT] At most {self.max_parallel} sub-agents '
                    f'may run in parallel per turn; {dropped} extra '
                    'delegation(s) were dropped. Issue the remaining ones on a '
                    'later turn.')))
