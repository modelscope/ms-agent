# Copyright (c) ModelScope Contributors. All rights reserved.
from typing import TYPE_CHECKING, List, Optional

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

if TYPE_CHECKING:
    from ms_agent.command.router import CommandRouter

logger = get_logger()


class InputCallback(Callback):
    """Waiting for human inputs. Supports slash command interception."""

    def __init__(
        self,
        config: DictConfig,
        command_router: Optional['CommandRouter'] = None,
    ):
        super().__init__(config)
        if command_router is None:
            command_router = self._build_default_router()
        self._command_router = command_router

    @staticmethod
    def _build_default_router() -> 'CommandRouter':
        from ms_agent.command import CommandRouter, register_builtin_commands

        router = CommandRouter()
        register_builtin_commands(router)
        return router

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role in ('tool', 'user'):
            return

        while True:
            query = input('>>> ').strip()
            if query:
                break

        if not query:
            runtime.should_stop = True
            return

        if self._command_router:
            handled = await self._try_command(query, runtime, messages)
            if handled:
                return

        runtime.should_stop = False
        messages.append(Message(role='user', content=query))

    async def _try_command(
        self,
        query: str,
        runtime: Runtime,
        messages: List[Message],
    ) -> bool:
        """Try to dispatch as slash command. Returns True if handled."""
        from ms_agent.command.router import CommandRouter
        from ms_agent.command.types import CommandContext, CommandResultType

        if not CommandRouter.is_command(query):
            return False

        cmd_name, args = CommandRouter.parse_input(query)
        ctx = CommandContext(
            raw_input=query,
            command_name=cmd_name,
            args=args,
            source='cli',
            runtime=runtime,
            extra={'router': self._command_router},
        )
        result = await self._command_router.dispatch(ctx)
        if result is None:
            return False

        if result.type == CommandResultType.QUIT:
            runtime.should_stop = True
        elif result.type == CommandResultType.MESSAGE:
            print(result.content)
        elif result.type == CommandResultType.SUBMIT_PROMPT:
            messages.append(Message(role='user', content=result.content))
            runtime.should_stop = False
        return True
