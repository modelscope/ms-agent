"""Resolve SafetyGuard ``ask`` decisions based on permission mode.

ask:          unchanged, so the user confirms
auto:         unchanged, so the model or agent decision provider confirms
full-access:  allow (uncertain calls pass; a hard deny never reaches here)
"""

from __future__ import annotations

from .config import normalize_permission_mode
from .shell_validator import SafetyDecision


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
    """Resolve a SafetyGuard ``ask`` into ``allow`` or keep ``ask``.

    Only processes decisions with ``action='ask'``; others pass through
    unchanged. ``read_policy`` is accepted so existing callers keep working;
    full-access allows an out-of-policy read instead of consulting it.
    """
    del read_policy
    if decision.action != 'ask':
        return decision

    canonical = normalize_permission_mode(mode)
    if canonical == 'full-access':
        return SafetyDecision(
            action='allow',
            reason=f'Allowed in full-access: {decision.reason}',
            category=decision.category,
        )
    return decision
