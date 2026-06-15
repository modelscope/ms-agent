"""CallbackToHookBridge — SessionStart only."""

from __future__ import annotations

from omegaconf import DictConfig
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.hooks.runtime import HookRuntime
from ms_agent.llm.utils import Message


class CallbackToHookBridge(Callback):
    def __init__(self, config: DictConfig, hook_runtime: HookRuntime) -> None:
        super().__init__(config)
        self._hooks = hook_runtime

    async def on_task_begin(
        self,
        runtime: Runtime,
        messages: List[Message],
    ) -> None:
        await self._hooks.run_session_start(runtime, messages)
