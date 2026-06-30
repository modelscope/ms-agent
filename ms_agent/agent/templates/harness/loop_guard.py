# Copyright (c) Alibaba, Inc. and its affiliates.
"""LoopGuardCallback -- detect and break invalid tool-call loops.

Generalized from deer-flow's LoopDetectionMiddleware (same thresholds and
two-layer design):
  - repeated-signature: the same (tool, stable-key) appears >= warn / hard times
    within a sliding window;
  - frequency: the same tool is called >= freq_warn / freq_hard times overall.

Detection runs in ``on_tool_call`` (fresh assistant tool_calls) but any injected
*user* message is emitted in ``after_tool_call`` -- injecting a user message
between an assistant's tool_calls and their tool results would be malformed.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, deque
from typing import List

from omegaconf import OmegaConf

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

logger = get_logger()

_WARN_MSG = (
    '[LOOP_GUARD] You are repeating the same kind of tool call without making '
    'progress. Stop and reassess: try a different approach or tool, or explain '
    'what is blocking you.')
_HARD_MSG = (
    '[LOOP_GUARD] Detected a repeated / high-frequency tool-call loop with no '
    'progress, so execution was stopped. Briefly tell the user what you were '
    'trying to do and where you got stuck.')


class LoopGuardCallback(Callback):
    """Config block (deer-flow defaults)::

        loop_guard:
          enabled: true
          window: 20
          warn: 3            # repeated-signature warn / hard
          hard: 5
          freq_warn: 30      # per-tool frequency warn / hard
          freq_hard: 50
          overrides:         # per-tool (freq_warn, freq_hard) overrides
            file_system---read_file: [120, 200]
    """

    def __init__(self, config):
        super().__init__(config)
        cfg = getattr(config, 'loop_guard', None)
        self.enabled = bool(getattr(cfg, 'enabled', True))
        self.window = int(getattr(cfg, 'window', 20))
        self.warn = int(getattr(cfg, 'warn', 3))
        self.hard = int(getattr(cfg, 'hard', 5))
        self.freq_warn = int(getattr(cfg, 'freq_warn', 30))
        self.freq_hard = int(getattr(cfg, 'freq_hard', 50))
        ov = getattr(cfg, 'overrides', None)
        self.overrides = {}
        if ov is not None:
            try:
                for k, v in (OmegaConf.to_container(ov, resolve=True)
                             or {}).items():
                    self.overrides[str(k)] = (int(v[0]), int(v[1]))
            except Exception:
                self.overrides = {}
        self._recent: deque = deque(maxlen=self.window)
        self._freq: Counter = Counter()
        self._warned = set()
        self._pending = None  # 'warn' | 'hard' | None

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _bare(name: str) -> str:
        return name.split('---')[-1] if name else ''

    def _stable_key(self, name: str, args) -> str:
        try:
            a = json.loads(args) if isinstance(args, str) else (args or {})
            if not isinstance(a, dict):
                a = {'_': str(a)}
        except Exception:
            a = {'_raw': str(args)}
        bare = self._bare(name)
        if bare in ('read_file', 'read'):
            path = str(
                a.get('path') or a.get('file') or a.get('file_path') or '')
            try:
                bucket = int(a.get('start') or a.get('start_line') or 0) // 200
            except Exception:
                bucket = 0
            return f'{path}#{bucket}'
        if bare in ('write_file', 'edit_file', 'str_replace', 'write', 'edit'):
            return self._hash(a)
        salient = {
            k: a[k]
            for k in ('path', 'file', 'file_path', 'url', 'query', 'command',
                      'cmd', 'pattern', 'glob') if k in a
        }
        return self._hash(salient or a)

    @staticmethod
    def _hash(obj) -> str:
        return hashlib.md5(
            json.dumps(obj, sort_keys=True,
                       default=str).encode('utf-8')).hexdigest()[:12]

    @staticmethod
    def _tc_field(tc, key):
        return tc.get(key, '') if isinstance(tc, dict) else getattr(
            tc, key, '')

    # ── lifecycle ──────────────────────────────────────────────────────────

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled or not messages:
            return
        m = messages[-1]
        if m.role != 'assistant' or not m.tool_calls:
            return
        for tc in m.tool_calls:
            name = self._tc_field(tc, 'tool_name')
            sig = (self._bare(name),
                   self._stable_key(name, self._tc_field(tc, 'arguments')))
            self._recent.append(sig)
            self._freq[sig[0]] += 1
            count = sum(1 for s in self._recent if s == sig)
            fw, fh = self.overrides.get(name, self.overrides.get(
                sig[0], (self.freq_warn, self.freq_hard)))
            if count >= self.hard or self._freq[sig[0]] >= fh:
                self._pending = 'hard'
                logger.warning('LoopGuard: hard limit on %s (count=%d freq=%d)',
                               sig, count, self._freq[sig[0]])
                return
            if count >= self.warn or self._freq[sig[0]] >= fw:
                key = sig if count >= self.warn else ('FREQ', sig[0])
                if key not in self._warned:
                    self._warned.add(key)
                    self._pending = 'warn'
                    logger.info('LoopGuard: warn on %s', sig)

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if self._pending is None:
            return
        pending, self._pending = self._pending, None
        if pending == 'hard':
            runtime.should_stop = True
            messages.append(Message(role='user', content=_HARD_MSG))
        elif pending == 'warn':
            messages.append(Message(role='user', content=_WARN_MSG))
