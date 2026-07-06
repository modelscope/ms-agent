"""Resolve SafetyGuard ``ask`` decisions based on permission mode.

auto mode:      per-category allow/deny (no interactive prompts)
strict mode:    all ask → deny
interactive:    ask unchanged (delegated to handler)
"""

from __future__ import annotations

from typing import Literal

from .shell_validator import SafetyDecision

_AUTO_CATEGORY_POLICY: dict[str, Literal['allow', 'deny']] = {
    'process_input_sub': 'allow',
    'process_output_sub': 'deny',
    'parse_failure': 'deny',
    'cd_write_compound': 'deny',
    'command_validator': 'deny',
    'shell_expansion': 'deny',
    'read_outside_dirs': 'deny',
}


def resolve_ask(
    decision: SafetyDecision,
    mode: str,
    read_policy: str = 'loose',
) -> SafetyDecision:
    """Resolve a SafetyGuard ``ask`` into ``allow`` or ``deny`` (or keep ``ask``).

    Only processes decisions with ``action='ask'``; others pass through unchanged.
    """
    if decision.action != 'ask':
        return decision

    if mode == 'strict':
        return SafetyDecision(
            action='deny',
            reason=f'Denied in strict mode: {decision.reason}',
            category=decision.category,
        )

    if mode == 'interactive':
        return decision

    # auto mode — resolve by category
    category = decision.category

    if category == 'read_outside_dirs':
        action: Literal['allow', 'deny'] = 'allow' if read_policy == 'loose' else 'deny'
        return SafetyDecision(
            action=action,
            reason=decision.reason,
            category=category,
        )

    resolved_action = _AUTO_CATEGORY_POLICY.get(category, 'deny')
    return SafetyDecision(
        action=resolved_action,
        reason=decision.reason,
        category=category,
    )
