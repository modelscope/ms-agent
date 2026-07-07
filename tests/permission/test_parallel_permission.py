# Copyright (c) ModelScope Contributors. All rights reserved.
"""Parallel tool calls (ToolManager.parallel_call_tool → asyncio.gather) must
not invoke the interactive permission handler concurrently: N prompts fighting
over one terminal deadlocks. The enforcer serializes asks."""
import asyncio

import pytest

from ms_agent.permission.config import PermissionConfig
from ms_agent.permission.enforcer import PermissionEnforcer
from ms_agent.permission.handler import PermissionAction, PermissionResponse
from ms_agent.permission.memory import PermissionMemory


class _ConcurrencyProbe:
    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    async def ask(self, tool_name, tool_args, context, suggestions=None):
        self.in_flight += 1
        self.calls += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.02)  # simulate a human deciding
        self.in_flight -= 1
        return PermissionResponse(action=PermissionAction.ALLOW_ONCE)


@pytest.mark.asyncio
async def test_parallel_asks_are_serialized(tmp_path):
    cfg = PermissionConfig.from_dict({'mode': 'restricted'})  # empty wl -> ask
    handler = _ConcurrencyProbe()
    enf = PermissionEnforcer(
        config=cfg, handler=handler,
        memory=PermissionMemory(project_path=str(tmp_path)))

    # 5 concurrent checks, like 5 parallel tool calls in one round.
    results = await asyncio.gather(
        *[enf.check('some_tool', {'i': i}) for i in range(5)])

    assert all(r.action == 'allow' for r in results)
    assert handler.calls == 5
    # The decisive assertion: asks never overlapped (was 5 before the fix).
    assert handler.max_in_flight == 1
