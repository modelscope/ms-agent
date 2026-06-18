# Copyright (c) ModelScope Contributors. All rights reserved.
from typing import TYPE_CHECKING, List, Optional
from omegaconf import DictConfig

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.command.interactive import InteractiveSession
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter

logger = get_logger()


class InputCallback(Callback):
    """Wait for human input mid-conversation, with slash-command support.

    This is a thin adapter over :class:`InteractiveSession`: it reuses the
    agent's single :class:`CommandRouter` (injected via ``command_router``)
    and delegates all ``>>>`` reading and slash-command handling to the shared
    session, so the initial-prompt path and this mid-turn path stay in lockstep.
    """

    def __init__(
        self,
        config: DictConfig,
        command_router: Optional['CommandRouter'] = None,
    ):
        super().__init__(config)
        if command_router is None:
            # Fallback for standalone / test instantiation. In normal CLI use
            # the agent injects its own router so there is a single instance.
            command_router = self._build_default_router()
        self._session = InteractiveSession(command_router)

    @staticmethod
    def _build_default_router() -> 'CommandRouter':
        from ms_agent.command import CommandRouter, register_builtin_commands

        router = CommandRouter()
        register_builtin_commands(router)
        return router

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role in ('tool', 'user'):
            return

        turn = await self._session.run_turn(messages=messages, runtime=runtime)
        if turn.action == 'quit':
            runtime.should_stop = True
            return
        runtime.should_stop = False
        messages.append(Message(role='user', content=turn.text))
