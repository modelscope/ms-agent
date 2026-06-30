# Copyright (c) Alibaba, Inc. and its affiliates.
"""RoundReminderCallback -- inject a convergence reminder before the round
budget runs out. Generalized from deep_research v2 searcher_callback.
"""
from __future__ import annotations

from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()

_DEFAULT_MESSAGE = (
    '[ROUND_REMINDER] You are on round <round> of at most <max_chat_round> '
    '(<remaining_rounds> left). Begin converging now: finish the current '
    'sub-goal, avoid opening new threads, and prepare your final answer.')


class RoundReminderCallback(Callback):
    """Inject a convergence reminder ``remind_before_max_round`` rounds before
    ``max_chat_round``.

    Config block::

        round_reminder:
          enabled: true
          remind_before_max_round: 2   # trigger at round == max_chat_round - this
          remind_at_round: null        # explicit override of the trigger round
          message: "..."               # optional; supports <round>,
                                       # <max_chat_round>, <remaining_rounds>
    """

    _MARK = '[ROUND_REMINDER]'

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'round_reminder', None)
        self.enabled = bool(getattr(cfg, 'enabled', False))
        self.remind_before = int(getattr(cfg, 'remind_before_max_round', 2))
        self.remind_at_round = getattr(cfg, 'remind_at_round', None)
        self.message = getattr(cfg, 'message', None)
        self.max_chat_round = int(getattr(config, 'max_chat_round', 0) or 0)

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        if not self.enabled:
            return
        trigger = self.remind_at_round
        if trigger is None:
            if not self.max_chat_round:
                return
            trigger = self.max_chat_round - self.remind_before
        if runtime.round != trigger:
            return
        # de-dup: skip if a reminder is already among the recent messages
        for m in messages[-10:]:
            if m.role == 'user' and isinstance(
                    m.content, str) and self._MARK in m.content:
                return
        remaining = max(0, self.max_chat_round
                        - runtime.round) if self.max_chat_round else 0
        text = self.message or _DEFAULT_MESSAGE
        text = (text.replace('<round>', str(runtime.round)).replace(
            '<max_chat_round>',
            str(self.max_chat_round)).replace('<remaining_rounds>',
                                              str(remaining)))
        if self._MARK not in text:
            text = self._MARK + ' ' + text
        messages.append(Message(role='user', content=text))
        logger.info('RoundReminderCallback: injected reminder at round %s',
                    runtime.round)
