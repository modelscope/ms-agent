# Copyright (c) Alibaba, Inc. and its affiliates.
"""Reusable harness callbacks for template agents.

These are generalized from deep_research v2's private callbacks so that any
template (or user config) can opt into them via ``callbacks:``.

Importing this module registers the callbacks into
``ms_agent.callbacks.callbacks_mapping`` (using ``setdefault`` so it never
clobbers existing entries), which lets templates reference
``callbacks: [round_reminder, stop_gate]`` WITHOUT ``trust_remote_code``.
"""
from .loop_guard import LoopGuardCallback
from .plan_check import PlanCheckCallback
from .round_reminder import RoundReminderCallback
from .state_inject import StateInjectCallback
from .stop_gate import StopGateCallback
from .subagent_limit import SubagentLimitCallback
from .todo_gate import TodoGateCallback

_HARNESS_CALLBACKS = {
    'round_reminder': RoundReminderCallback,
    'stop_gate': StopGateCallback,
    'state_inject': StateInjectCallback,
    'loop_guard': LoopGuardCallback,
    'todo_gate': TodoGateCallback,
    'plan_check': PlanCheckCallback,
    'subagent_limit': SubagentLimitCallback,
}


def register_harness_callbacks() -> None:
    """Idempotently register harness callbacks into the global mapping."""
    try:
        from ms_agent.callbacks import callbacks_mapping
        for name, cls in _HARNESS_CALLBACKS.items():
            callbacks_mapping.setdefault(name, cls)
    except Exception:  # pragma: no cover - registration is best-effort
        pass


register_harness_callbacks()

__all__ = [
    'RoundReminderCallback',
    'StopGateCallback',
    'StateInjectCallback',
    'LoopGuardCallback',
    'TodoGateCallback',
    'PlanCheckCallback',
    'SubagentLimitCallback',
    'register_harness_callbacks',
]
