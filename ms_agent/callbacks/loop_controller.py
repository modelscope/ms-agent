# Copyright (c) ModelScope Contributors. All rights reserved.
"""In-session ``/loop`` controller (loop engineering).

Turns the "wait for human input" fork after a completed turn into "ask an
automatic policy". It is registered as a :class:`Callback` *before*
:class:`~ms_agent.callbacks.input_callback.InputCallback` so that, when a loop
is active, it re-injects the next iteration's prompt (appends a ``user`` message
and clears ``should_stop``). That makes ``InputCallback.after_tool_call`` a
no-op for the same turn, because it returns early when the last message role is
``user`` -- so we get automatic re-prompting with zero changes to the
human-input path.

Modes (set by the ``/loop`` command onto :class:`Runtime`):
  - ``interval``:    fixed delay between iterations (``runtime.loop_interval``).
  - ``self_paced``:  the model calls the ``schedule_wakeup`` tool each turn to
                     choose the next delay; not calling it ends the loop.
  - ``maintenance``: like ``self_paced`` but seeded with a default prompt.

Guardrails (any one trips the breaker -> stop): hard iteration cap, wall-clock
deadline, optional token budget, and no-progress detection. Ctrl+C during the
sleep cancels the loop via ``run_loop``'s existing ``KeyboardInterrupt``
handling.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import time
from typing import TYPE_CHECKING, List, Optional

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter

logger = get_logger()

# Self-paced delays are clamped to this band (seconds): responsive when busy,
# backed off when idle. Mirrors the widely documented ScheduleWakeup bounds.
MIN_DELAY = 60
MAX_DELAY = 3600
# Interval mode honors the user's cadence but floors tiny values so a runaway
# loop cannot hammer the model. Sub-minute intervals are allowed because the
# user asked for them explicitly.
MIN_INTERVAL = 1
# Stop after this many consecutive identical final answers.
NO_PROGRESS_LIMIT = 3

# Appended to each self-paced/maintenance iteration so the model keeps choosing
# a cadence (or stops cleanly by not scheduling).
SELF_PACED_SUFFIX = (
    '\n\n[loop] This task runs on a self-paced loop. When you finish this '
    'iteration, decide whether more work remains. If it does, call the '
    '`schedule_wakeup` tool with the number of seconds to wait before the next '
    'iteration (60-3600) and a brief reason. If the task is verifiably '
    'complete, do NOT call schedule_wakeup -- that ends the loop cleanly.')


async def expand_slash_body(router, runtime, messages, body: str) -> str:
    """Expand a ``/slash`` loop body through the router into its submit prompt.

    A skill/plugin command body is re-rendered so its content stays fresh each
    iteration. Returns the raw text unchanged when there is no router, the token
    is not a recognized command, or dispatch does not yield a submit prompt.
    """
    text = (body or '').strip()
    if not text.startswith('/') or router is None:
        return body
    try:
        if not router.is_command(text):
            return body
        from ms_agent.command.types import (CommandContext,
                                            CommandResultType)
        cmd_name, args = router.parse_input(text)
        ctx = CommandContext(
            raw_input=text,
            command_name=cmd_name,
            args=args,
            runtime=runtime,
            extra={
                'router': router,
                'messages': messages if messages is not None else [],
            },
        )
        result = await router.dispatch(ctx)
    except Exception as e:  # noqa: BLE001 - loop must not crash on expand
        logger.warning('[loop] failed to expand slash body %r: %s', text, e)
        return body
    if result is not None and result.type == CommandResultType.SUBMIT_PROMPT:
        return result.content
    return body


async def build_iteration_prompt(router, runtime, messages, body: str) -> str:
    """Build one iteration's user prompt: expand a slash body, then, for
    self-paced/maintenance modes, append the schedule_wakeup guidance.
    """
    expanded = await expand_slash_body(router, runtime, messages, body)
    if getattr(runtime, 'loop_mode', '') in ('self_paced', 'maintenance'):
        return f'{expanded}{SELF_PACED_SUFFIX}'
    return expanded


class LoopController(Callback):
    """Decision box for the in-session ``/loop``."""

    def __init__(self,
                 config,
                 command_router: Optional['CommandRouter'] = None,
                 event_sink: object = None):
        super().__init__(config)
        self._router = command_router
        self._event_sink = event_sink
        # Wakeup requested by the schedule_wakeup tool during the current turn.
        # ``_wakeup_requested`` False means the model did not schedule a next
        # run -> clean stop for self-paced modes.
        self._pending_delay: Optional[int] = None
        self._pending_reason: str = ''
        self._wakeup_requested: bool = False
        # No-progress tracking: fingerprints of recent final answers.
        self._recent_fingerprints: List[str] = []

    # -- schedule_wakeup tool seam ------------------------------------------

    def request_wakeup(self, delay_seconds: int, reason: str = '') -> int:
        """Record the model's chosen next delay (called by ``schedule_wakeup``).

        Returns the clamped delay actually recorded so the tool can echo it.
        """
        try:
            raw = int(delay_seconds)
        except (TypeError, ValueError):
            raw = MIN_DELAY
        delay = self._clamp(raw, MIN_DELAY, MAX_DELAY)
        self._pending_delay = delay
        self._pending_reason = reason or ''
        self._wakeup_requested = True
        return delay

    def start_iteration_window(self) -> None:
        """Reset the per-turn wakeup signal before a self-paced iteration."""
        self._pending_delay = None
        self._pending_reason = ''
        self._wakeup_requested = False

    # -- Callback ------------------------------------------------------------

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        # Only act at the "would stop" fork: the model produced a final answer
        # (no pending tool calls) and the last message is not tool/user output.
        if not messages:
            return
        last = messages[-1]
        if getattr(last, 'tool_calls', None) or last.role in ('tool', 'user'):
            return
        if not getattr(runtime, 'loop_active', False):
            return  # not looping -> let InputCallback wait for a human

        # Terminate? Leaving should_stop as-is (True, set by
        # LLMAgent.after_tool_call before callbacks run) hands control back to
        # InputCallback (attended) or ends the run (headless).
        reason = self._should_terminate(runtime, last)
        if reason is not None:
            self._end(runtime, reason)
            return

        delay = self._resolve_delay(runtime)
        if delay is None:
            # self_paced/maintenance: model chose not to schedule again -> done.
            self._end(runtime, 'complete (model did not reschedule)')
            return

        iteration = runtime.loop_iteration + 1
        note = runtime.loop_next_reason or self._pending_reason
        self._emit(f'[loop #{iteration}] next in {delay}s'
                   + (f' -- {note}' if note else ''))

        try:
            await self._sleep(delay)
        except asyncio.CancelledError:
            self._end(runtime, 'cancelled')
            raise
        except KeyboardInterrupt:
            self._end(runtime, 'interrupted')
            raise

        next_prompt = await build_iteration_prompt(self._router, runtime,
                                                   messages, runtime.loop_prompt)
        runtime.loop_iteration = iteration
        runtime.loop_next_delay = None
        runtime.loop_next_reason = ''
        runtime.should_stop = False
        # Fresh wakeup window for the upcoming self-paced iteration.
        self.start_iteration_window()
        messages.append(Message(role='user', content=next_prompt))

    # -- helpers -------------------------------------------------------------

    def _resolve_delay(self, runtime: Runtime) -> Optional[int]:
        if runtime.loop_mode == 'interval':
            base = runtime.loop_interval or MIN_DELAY
            return max(MIN_INTERVAL, int(base))
        # self_paced / maintenance: the model must call schedule_wakeup.
        if self._wakeup_requested and self._pending_delay is not None:
            runtime.loop_next_delay = self._pending_delay
            runtime.loop_next_reason = self._pending_reason
            return self._pending_delay
        # Fallback to a persisted decision (e.g. restored mid-sleep on resume).
        if runtime.loop_next_delay is not None:
            return self._clamp(
                int(runtime.loop_next_delay), MIN_DELAY, MAX_DELAY)
        return None

    def _should_terminate(self, runtime: Runtime,
                          last: Message) -> Optional[str]:
        if runtime.loop_iteration >= runtime.loop_max:
            return f'max iterations ({runtime.loop_max}) reached'
        if (runtime.loop_deadline is not None
                and time.time() >= runtime.loop_deadline):
            return 'deadline reached (auto-expired)'
        budget = runtime.loop_token_budget
        if budget is not None:
            used = self._tokens_used(runtime)
            if used is not None and used >= budget:
                return f'token budget ({budget:,}) exhausted'
        if self._no_progress(last):
            return f'no progress for {NO_PROGRESS_LIMIT} iterations'
        return None

    def _no_progress(self, last: Message) -> bool:
        content = last.content if isinstance(last.content, str) else ''
        fp = hashlib.md5(content.strip().encode('utf-8')).hexdigest()
        self._recent_fingerprints.append(fp)
        if len(self._recent_fingerprints) > NO_PROGRESS_LIMIT:
            self._recent_fingerprints.pop(0)
        return (len(self._recent_fingerprints) >= NO_PROGRESS_LIMIT
                and len(set(self._recent_fingerprints)) == 1)

    @staticmethod
    def _tokens_used(runtime: Runtime) -> Optional[int]:
        try:
            from ms_agent.agent.llm_agent import LLMAgent
            total = (LLMAgent.TOTAL_PROMPT_TOKENS
                     + LLMAgent.TOTAL_COMPLETION_TOKENS)
        except Exception:
            return None
        used = total - int(getattr(runtime, 'loop_token_start', 0) or 0)
        return used if used >= 0 else 0

    async def _sleep(self, delay: int) -> None:
        await asyncio.sleep(self._with_jitter(delay))

    @staticmethod
    def _with_jitter(delay: int) -> float:
        # Small +/-10% jitter (capped at 30s) to spread API load across runs.
        jitter = min(delay * 0.1, 30)
        return max(0.0, delay + random.uniform(-jitter, jitter))

    @staticmethod
    def _clamp(value: int, low: int, high: int) -> int:
        return max(low, min(high, value))

    def _end(self, runtime: Runtime, reason: str) -> None:
        runtime.reset_loop()
        self.start_iteration_window()
        self._recent_fingerprints.clear()
        self._emit(f'[loop] stopped: {reason}')

    def _emit(self, text: str) -> None:
        if self._event_sink is not None:
            try:
                from ms_agent.ui.events import Notice
                self._event_sink.emit(Notice(level='info', text=text))
                return
            except Exception:  # noqa: BLE001 - fall back to stdout
                pass
        print(text)
