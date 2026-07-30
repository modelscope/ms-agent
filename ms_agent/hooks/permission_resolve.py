"""Merge PreToolUse hook decisions with PermissionEnforcer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ms_agent.hooks.events import HookResult
from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionDecision, PermissionEnforcer
from ms_agent.permission.matcher import PermissionMatcher

if TYPE_CHECKING:
    from ms_agent.hooks.runtime import HookRuntime


async def check_rule_based_permissions(
    tool_name: str,
    tool_args: dict[str, Any],
    config: PermissionConfig,
    matcher: PermissionMatcher | None = None,
) -> PermissionDecision | None:
    """Rule layer only: blacklist deny, explicit ask rules. No handler popup."""
    m = matcher or PermissionMatcher()
    for pattern in config.blacklist:
        if m.match_with_content(pattern, tool_name, tool_args):
            return PermissionDecision(
                action='deny',
                reason=f'Denied by blacklist rule: {pattern}',
            )
    for pattern in config.ask_rules:
        if m.match_with_content(pattern, tool_name, tool_args):
            return PermissionDecision(
                action='ask',
                reason=f'Ask rule matched: {pattern}',
            )
    return None


async def _run_permission_request_hook(
    hook_runtime: HookRuntime | None,
    tool_name: str,
    tool_args: dict[str, Any],
    permission_config: PermissionConfig | None,
) -> HookResult | None:
    if hook_runtime is None or hook_runtime.is_empty:
        return None
    if permission_config is None or permission_config.mode != 'interactive':
        return None
    if not hook_runtime.registry.get_handlers('PermissionRequest', tool_name):
        return None
    return await hook_runtime.run_permission_request(tool_name, tool_args)


async def resolve_hook_permission_decision(
    hook_result: HookResult | None,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    permission_enforcer: PermissionEnforcer | None,
    permission_config: PermissionConfig | None,
    hook_runtime: HookRuntime | None = None,
    force_decision: PermissionDecision | None = None,
    call_id: str = '',
) -> PermissionDecision | str:
    # ``force_decision`` carries a SafetyGuard ``ask`` (interactive): it must
    # reach the handler even when whitelist/memory would otherwise allow, so a
    # broad whitelist can't silently bypass a safety confirmation (REVIEW P1-2).
    if hook_result and hook_result.action == 'deny':
        return f'Blocked by hook: {hook_result.reason}'

    args = (
        hook_result.updated_args
        if hook_result and hook_result.updated_args else tool_args)

    if hook_result and hook_result.action == 'allow':
        if permission_config:
            rule = await check_rule_based_permissions(tool_name, args,
                                                      permission_config)
            if rule and rule.action == 'deny':
                return rule
            if rule and rule.action == 'ask':
                if permission_enforcer:
                    return await permission_enforcer.check(
                        tool_name, args, force_decision=rule,
                        call_id=call_id)
        return PermissionDecision(
            action='allow',
            reason=hook_result.reason or 'Allowed by PreToolUse hook',
        )

    if hook_result and hook_result.action == 'ask':
        if permission_enforcer:
            return await permission_enforcer.check(
                tool_name,
                args,
                force_decision=PermissionDecision(
                    action='ask', reason=hook_result.reason),
                call_id=call_id,
            )

    pr = await _run_permission_request_hook(hook_runtime, tool_name, args,
                                            permission_config)
    if pr and pr.action == 'deny':
        return f'Blocked by hook: {pr.reason}'
    if pr and pr.action == 'ask' and permission_enforcer:
        return await permission_enforcer.check(
            tool_name,
            args,
            force_decision=PermissionDecision(
                action='ask', reason=pr.reason),
            call_id=call_id,
        )

    if permission_enforcer:
        return await permission_enforcer.check(
            tool_name, args, force_decision=force_decision, call_id=call_id)
    return PermissionDecision(action='allow', reason='No permission enforcer')
