"""Normalize stdout/HTTP hook responses from multiple ecosystems."""

from __future__ import annotations

import json
from typing import Any

from ms_agent.hooks.events import HookResult


class ResponseAdapter:
    """Parse hook stdout JSON into a canonical HookResult."""

    def parse(
        self,
        stdout_text: str,
        exit_code: int = 0,
        stderr_text: str = '',
        event: str | None = None,
    ) -> HookResult:
        if not stdout_text:
            return HookResult(action='pass', exit_code=exit_code, stderr=stderr_text)

        try:
            data = json.loads(stdout_text)
        except json.JSONDecodeError:
            return HookResult(
                action='error',
                reason=f'Invalid JSON in hook stdout: {stdout_text[:200]}',
                exit_code=exit_code,
                stderr=stderr_text,
            )

        if not isinstance(data, dict):
            return HookResult(action='pass', exit_code=exit_code)

        return self._normalize_dict(data, event, exit_code, stderr_text)

    def _normalize_dict(
        self,
        data: dict[str, Any],
        event: str | None,
        exit_code: int,
        stderr_text: str,
    ) -> HookResult:
        updated_args = (
            data.get('updatedArgs')
            or data.get('updated_input')
            or data.get('updatedInput')
        )
        if updated_args is not None and not isinstance(updated_args, dict):
            updated_args = None

        additional_context = (
            data.get('additionalContext')
            or data.get('additional_context')
            or data.get('agent_message')
            or data.get('context')
            or ''
        )

        # Claude hookSpecificOutput
        hso = data.get('hookSpecificOutput')
        if isinstance(hso, dict):
            perm = hso.get('permissionDecision')
            if perm:
                action = self._map_permission(perm)
                return HookResult(
                    action=action,
                    reason=data.get('reason', '') or hso.get('reason', ''),
                    additional_context=additional_context,
                    updated_args=updated_args or hso.get('updatedInput'),
                    exit_code=exit_code,
                    stderr=stderr_text,
                )
            if hso.get('updatedInput'):
                updated_args = hso['updatedInput']

        # Direct decision fields
        decision = data.get('decision') or data.get('permission')
        action_field = data.get('action')
        if decision:
            action = self._map_decision(str(decision))
            return HookResult(
                action=action,
                reason=data.get('reason', '') or data.get('user_message', ''),
                additional_context=additional_context,
                updated_args=updated_args,
                exit_code=exit_code,
                stderr=stderr_text,
            )
        if action_field in ('block', 'deny'):
            return HookResult(
                action='deny',
                reason=data.get('reason', '') or data.get('message', ''),
                additional_context=additional_context,
                updated_args=updated_args,
                exit_code=exit_code,
                stderr=stderr_text,
            )

        # Only updated_args without permission decision -> passthrough
        if updated_args is not None:
            return HookResult(
                action='pass',
                additional_context=additional_context,
                updated_args=updated_args,
                exit_code=exit_code,
                stderr=stderr_text,
            )

        if additional_context:
            return HookResult(
                action='pass',
                additional_context=additional_context,
                exit_code=exit_code,
                stderr=stderr_text,
            )

        # Stop event: continue=false means allow stop (pass)
        if event == 'Stop' and data.get('continue') is False:
            return HookResult(action='pass', exit_code=exit_code)

        # Cursor stop followup_message -> block
        if event == 'Stop' and data.get('followup_message'):
            return HookResult(
                action='block',
                reason=str(data['followup_message']),
                exit_code=exit_code,
            )

        return HookResult(action='pass', exit_code=exit_code, stderr=stderr_text)

    @staticmethod
    def _map_decision(decision: str) -> str:
        d = decision.lower()
        if d in ('deny', 'block', 'reject'):
            return 'deny'
        if d in ('allow', 'approve', 'permit'):
            return 'allow'
        if d == 'ask':
            return 'ask'
        return 'pass'

    @staticmethod
    def _map_permission(perm: str) -> str:
        p = perm.lower()
        if p == 'deny':
            return 'deny'
        if p == 'allow':
            return 'allow'
        if p == 'ask':
            return 'ask'
        return 'pass'
