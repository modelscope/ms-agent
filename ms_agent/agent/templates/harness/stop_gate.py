# Copyright (c) Alibaba, Inc. and its affiliates.
"""StopGateCallback -- run checks before honoring the agent's decision to stop;
on failure, inject a reflection message and force another round (bounded by
``max_retries``). Generalized from deep_research v2 researcher_callback.
"""
from __future__ import annotations

import os
from typing import List, Optional

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

from .quality_check import LLMQualityChecker

logger = get_logger()

_DEFAULT_REFLECT = (
    'Before finishing: an automated check found an issue -- {reason}. '
    'Please address it and continue; do not stop yet.')


class StopGateCallback(Callback):
    """Gate the agent's stop decision behind a chain of checks.

    Config block::

        stop_gate:
          enabled: true
          max_retries: 2
          output_dir: null            # base for relative artifact paths
          checks:
            - type: artifact_exists
              path: final_report.md
            - type: min_size_ratio
              path: final_report.md
              baseline: reports/draft.md
              min_ratio: 0.5
            - type: llm_quality
              path: null              # null -> audit the last assistant message
              model: qwen3.7-plus
              message: "..."          # optional reflection; supports {reason}
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'stop_gate', None)
        self.enabled = bool(getattr(cfg, 'enabled', False))
        self.max_retries = int(getattr(cfg, 'max_retries', 2))
        base = getattr(cfg, 'output_dir', None)
        self.base_dir = base or getattr(config, 'output_dir', None) or '.'
        self.checks = list(getattr(cfg, 'checks', None) or [])
        self._llm = getattr(config, 'llm', None)
        self._retries_used = 0

    # ---- helpers -----------------------------------------------------------

    def _resolve(self, path) -> Optional[str]:
        if not path:
            return None
        return path if os.path.isabs(path) else os.path.join(
            self.base_dir, path)

    @staticmethod
    def _last_assistant_text(messages: List[Message]) -> str:
        for m in reversed(messages):
            if m.role == 'assistant' and isinstance(
                    m.content, str) and m.content.strip():
                return m.content
        return ''

    def _run_check(self, check, messages: List[Message]) -> Optional[str]:
        ctype = getattr(check, 'type', None)
        path = self._resolve(getattr(check, 'path', None))

        if ctype == 'artifact_exists':
            if not path or not os.path.isfile(path):
                return (getattr(check, 'message', None)
                        or f'expected artifact not found: '
                        f'{getattr(check, "path", path)}')
            return None

        if ctype == 'min_size_ratio':
            baseline = self._resolve(getattr(check, 'baseline', None))
            min_ratio = float(getattr(check, 'min_ratio', 0.5))
            if not path or not os.path.isfile(path):
                return getattr(check, 'message',
                               None) or 'expected artifact not found'
            cur = os.path.getsize(path)
            base = os.path.getsize(baseline) if (
                baseline and os.path.isfile(baseline)) else 0
            if base and (cur / base) < min_ratio:
                return getattr(
                    check, 'message',
                    None) or 'the final artifact looks over-compressed'
            return None

        if ctype == 'llm_quality':
            if path and os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = self._last_assistant_text(messages)
            if not content.strip():
                return None
            model = str(
                getattr(check, 'model', None)
                or getattr(self._llm, 'model', 'qwen3.5-plus'))
            api_key = getattr(check, 'openai_api_key', None) or getattr(
                self._llm, 'openai_api_key', None)
            base_url = getattr(check, 'openai_base_url', None) or getattr(
                self._llm, 'openai_base_url', None)
            checker = LLMQualityChecker(model, api_key, base_url,
                                        getattr(check, 'system_prompt', None))
            return checker.check(content)

        logger.warning('StopGateCallback: unknown check type %r', ctype)
        return None

    # ---- lifecycle ---------------------------------------------------------

    async def after_tool_call(self, runtime: Runtime,
                              messages: List[Message]):
        if not self.enabled or not self.checks:
            return
        if not runtime.should_stop:
            return
        if self._retries_used >= self.max_retries:
            return
        for check in self.checks:
            try:
                reason = self._run_check(check, messages)
            except Exception as exc:  # pragma: no cover
                logger.warning('StopGateCallback: check raised %s', exc)
                reason = None
            if reason:
                tmpl = getattr(check, 'message', None) or _DEFAULT_REFLECT
                text = tmpl.replace('{reason}',
                                    reason) if '{reason}' in tmpl else tmpl
                messages.append(Message(role='user', content=text))
                runtime.should_stop = False
                self._retries_used += 1
                logger.info(
                    'StopGateCallback: gate failed (%s); forcing another '
                    'round (%d/%d)', reason, self._retries_used,
                    self.max_retries)
                return
