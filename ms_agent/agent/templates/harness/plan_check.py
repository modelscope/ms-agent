# Copyright (c) Alibaba, Inc. and its affiliates.
"""PlanCheckCallback -- completeness self-check when a plan is first created.

When the agent creates a plan (first ``todo_write`` call), this captures it and
runs a lightweight LLM completeness check against the user's original request,
then injects a single user message with concrete feedback (or nothing if the
plan looks complete). This is the *creation-time* half of plan completeness; the
*stop-time* half is ``TodoGateCallback``.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

from .quality_check import LLMQualityChecker

logger = get_logger()

_PLAN_RUBRIC = (
    "You audit a freshly-created task plan against the user's request. PASS if "
    'the plan covers the request\'s key requirements and each step is concrete '
    'and verifiable. FAIL only if there are clear gaps: a stated requirement is '
    'missing, steps are vague with no way to verify them, or the scope is wrong. '
    'Wording, ordering, and style are out of scope.\n'
    'Respond with EXACTLY one JSON object and nothing else: {"pass": true} or '
    '{"pass": false, "reason": "<= two sentences naming the concrete gap(s)>"}.')


class PlanCheckCallback(Callback):
    """Config block::

        plan_check:
          enabled: true
          model: qwen3.7-plus     # judge model (defaults to the agent's llm)
          plan_file: plan.json
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'plan_check', None)
        self.enabled = bool(getattr(cfg, 'enabled', True))
        self.plan_file = str(getattr(cfg, 'plan_file', 'plan.json'))
        self.output_dir = getattr(config, 'output_dir', None) or '.'
        self._llm = getattr(config, 'llm', None)
        self._model = getattr(cfg, 'model', None)
        self._checked = False
        self._user_request: Optional[str] = None

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        for m in messages:
            if m.role == 'user' and isinstance(m.content,
                                               str) and m.content.strip():
                self._user_request = m.content
                break

    def _read_plan_text(self) -> str:
        path = self.plan_file if os.path.isabs(self.plan_file) else os.path.join(
            self.output_dir, self.plan_file)
        if not os.path.isfile(path):
            return ''
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            return ''
        todos = data.get('todos') if isinstance(data, dict) else data
        if not todos:
            return ''
        lines = []
        for t in todos:
            t = t or {}
            lines.append(
                f"- [{t.get('status', '?')}] {t.get('content', '')}")
        return '\n'.join(lines)

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled or self._checked:
            return
        # Find the most recent assistant message that issued tool calls.
        assistant = None
        for m in reversed(messages):
            if m.role == 'assistant' and m.tool_calls:
                assistant = m
                break
        if assistant is None:
            return
        wrote_plan = any(
            str((tc.get('tool_name', '') if isinstance(tc, dict) else getattr(
                tc, 'tool_name', ''))).endswith('todo_write')
            for tc in assistant.tool_calls)
        if not wrote_plan:
            return
        self._checked = True  # only judge the first plan creation

        plan_text = self._read_plan_text()
        if not plan_text.strip():
            return
        content = (f'User request:\n{self._user_request or "(unknown)"}\n\n'
                   f'Plan:\n{plan_text}')
        model = str(
            self._model or getattr(self._llm, 'model', 'qwen3.5-plus'))
        api_key = getattr(self._llm, 'openai_api_key', None)
        base_url = getattr(self._llm, 'openai_base_url', None)
        try:
            reason = LLMQualityChecker(model, api_key, base_url,
                                       _PLAN_RUBRIC).check(content)
        except Exception as exc:  # pragma: no cover
            logger.warning('PlanCheck: judge failed: %s', exc)
            return
        if reason:
            messages.append(
                Message(
                    role='user',
                    content=(
                        f'[PLAN_CHECK] Your plan looks incomplete: {reason} '
                        'Please revise the plan (todo_write) to close these '
                        'gaps before proceeding.')))
            logger.info('PlanCheck: injected feedback: %s', reason)
