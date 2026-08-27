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
    # Running code is what full access is FOR. Refusing every `python3 -c` in
    # the mode whose whole meaning is "stop asking me" would make the mode
    # useless, and the confirmation this category exists for is the one an
    # interactive user gets. What auto mode cannot honestly claim is that it
    # inspected the code — hence the message on the ask, and the setting-page
    # copy that says so.
    'interpreter_exec': 'allow',
    # A private key does not become less private because the user is not
    # watching. There is no path here that reads it without someone deciding.
    'sensitive_read': 'deny',
}


#: Safety confirmations a standing answer may satisfy.
#:
#: The rest are deliberately not here. "This reads a private key" has to be
#: decided each time, because what makes it risky is the specific file, and a
#: pattern broad enough to remember would cover files the user never saw.
#: "This runs code I cannot analyse" is different: every inline `python3 -c` is
#: the same decision, it comes up constantly, and an ask the user cannot settle
#: is one they answer by turning confirmations off — which is the outcome the
#: confirmation existed to prevent.
REMEMBERABLE_ASK_CATEGORIES: frozenset = frozenset({'interpreter_exec'})


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
        action: Literal['allow',
                        'deny'] = 'allow' if read_policy == 'loose' else 'deny'
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
