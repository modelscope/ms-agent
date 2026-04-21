"""Fine-grained permission policies for ACP tool calls.

Policies control how ms-agent handles ``request_permission`` when a tool
call is about to execute.

Supported policies:
  - ``auto_approve``: silently approve everything (dev/testing)
  - ``always_ask``: always prompt the client for approval
  - ``remember_choice``: ask once per tool name, remember the answer
"""

from __future__ import annotations
from typing import Any, Dict, Optional

from ms_agent.utils.logger import get_logger

logger = get_logger()


class PermissionPolicy:
    """Manages permission decisions for tool calls within a session."""

    def __init__(self, policy: str = 'auto_approve'):
        self.policy = policy
        self._remembered: Dict[str, bool] = {}

    def should_ask(self, tool_name: str) -> bool:
        """Return True if the client should be asked for this tool call."""
        if self.policy == 'auto_approve':
            return False
        if self.policy == 'remember_choice':
            return tool_name not in self._remembered
        return True  # always_ask

    def auto_decision(self, tool_name: str) -> str | None:
        """Return a pre-determined decision if available.

        Returns ``'allow_once'`` for auto-approve, the remembered outcome
        for remember_choice, or ``None`` if the client must be asked.
        """
        if self.policy == 'auto_approve':
            return 'allow_once'
        if self.policy == 'remember_choice' and tool_name in self._remembered:
            return 'allow_always' if self._remembered[
                tool_name] else 'deny_once'
        return None

    def record_choice(self, tool_name: str, allowed: bool) -> None:
        """Record a user's permission decision for future lookups."""
        if self.policy == 'remember_choice':
            self._remembered[tool_name] = allowed
            logger.info('Permission remembered for %s: %s', tool_name,
                        'allowed' if allowed else 'denied')

    def reset(self) -> None:
        """Clear all remembered decisions."""
        self._remembered.clear()


async def request_tool_permission(
    connection,
    session_id: str,
    tool_call_id: str,
    tool_name: str,
    policy: PermissionPolicy,
) -> bool:
    """Execute the permission flow for a tool call.

    Returns ``True`` if the tool should proceed, ``False`` if denied.
    """
    decision = policy.auto_decision(tool_name)
    if decision is not None:
        return 'allow' in decision

    from acp.schema import PermissionOption, ToolCall
    options = [
        PermissionOption(
            option_id='allow_once', name='Allow', kind='allow_once'),
        PermissionOption(
            option_id='allow_always', name='Always allow',
            kind='allow_always'),
        PermissionOption(
            option_id='deny_once', name='Deny', kind='reject_once'),
    ]
    tool_call = ToolCall(
        tool_call_id=tool_call_id,
        title=tool_name,
        status='pending',
    )

    try:
        result = await connection.request_permission(
            session_id=session_id,
            tool_call=tool_call,
            options=options,
        )
        outcome = getattr(result, 'outcome', None)
        if outcome is None:
            return True

        outcome_type = getattr(outcome, 'outcome', '')
        if outcome_type == 'cancelled':
            policy.record_choice(tool_name, False)
            return False

        selected_id = getattr(outcome, 'option_id', '')
        allowed = 'allow' in selected_id
        policy.record_choice(tool_name, allowed)
        return allowed

    except Exception:
        logger.warning('Permission request failed for %s, auto-approving',
                       tool_name)
        return True
