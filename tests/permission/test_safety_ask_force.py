# Copyright (c) ModelScope Contributors. All rights reserved.
"""REVIEW P1-2: a SafetyGuard `ask` (passed as force_decision) must reach the
handler even when a whitelist/memory entry would otherwise allow the tool."""
import pytest

from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionDecision, PermissionEnforcer
from ms_agent.permission.memory import PermissionMemory


class _RecordingHandler:
    def __init__(self):
        self.asked = False

    async def ask(self, tool_name, tool_args, context, suggestions=None):
        self.asked = True
        from ms_agent.permission.handler import (PermissionAction,
                                                 PermissionResponse)
        return PermissionResponse(action=PermissionAction.DENY)


@pytest.mark.asyncio
async def test_force_ask_not_bypassed_by_whitelist(tmp_path):
    cfg = PermissionConfig.from_dict({
        'mode': 'interactive',
        'whitelist': ['code_executor---shell_executor:*'],
    })
    handler = _RecordingHandler()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))
    force = PermissionDecision(action='ask', reason='safety')
    out = await enf.check(
        'code_executor---shell_executor', {'command': 'ls'},
        force_decision=force)
    # whitelist would allow, but the safety force_decision routed to the handler
    assert handler.asked is True
    assert out.action == 'deny'


@pytest.mark.asyncio
async def test_whitelist_allows_without_force(tmp_path):
    cfg = PermissionConfig.from_dict({
        'mode': 'interactive',
        'whitelist': ['code_executor---shell_executor:*'],
    })
    handler = _RecordingHandler()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))
    out = await enf.check('code_executor---shell_executor', {'command': 'ls'})
    assert handler.asked is False and out.action == 'allow'
