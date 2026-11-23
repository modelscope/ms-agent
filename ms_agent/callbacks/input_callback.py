# Copyright (c) ModelScope Contributors. All rights reserved.
from omegaconf import DictConfig
from typing import TYPE_CHECKING, List, Optional

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
        input_source: object = None,
        event_sink: object = None,
        persist_context: object = None,
    ):
        super().__init__(config)
        if command_router is None:
            # Fallback for standalone / test instantiation. In normal CLI use
            # the agent injects its own router so there is a single instance.
            command_router = self._build_default_router()
        # Kept for non-blocking steering polls (see _inject_steering); the
        # InteractiveSession also holds it for the idle re-prompt path.
        self._input_source = input_source
        # Steering echoes a folded-in user turn on this sink (see
        # _emit_steered_echo); the InteractiveSession holds the same sink for the
        # idle-prompt UserMessage echo.
        self._event_sink = event_sink
        self._session = InteractiveSession(
            command_router,
            source='tui' if input_source is not None else 'cli',
            input_source=input_source,
            event_sink=event_sink,
            persist_context=persist_context)

    @staticmethod
    def _build_default_router() -> 'CommandRouter':
        from ms_agent.command import CommandRouter, register_builtin_commands

        router = CommandRouter()
        register_builtin_commands(router)
        return router

    def _inject_steering(self, runtime: Runtime,
                         messages: List[Message]) -> None:
        """Inject queued plain messages into the live turn without stopping it.

        Called at a safe mid-turn boundary (tool results already complete). The
        input source decides what is steerable: in 'steer' mode it returns the
        leading plain messages, leaving commands to run at idle. A source
        without ``poll_steering`` (CLI, WebUI) makes this a no-op, so the
        existing behavior is unchanged.
        """
        poll = getattr(self._input_source, 'poll_steering', None)
        if not callable(poll):
            return
        try:
            lines = poll() or []
        except Exception:  # noqa: BLE001 - steering must never break the loop
            return
        injected = False
        for text in lines:
            if isinstance(text, str) and text.strip():
                messages.append(Message(role='user', content=text))
                self._emit_steered_echo(text)
                injected = True
        if injected:
            # Keep the turn alive so the model sees the injected messages on the
            # next iteration instead of stopping.
            runtime.should_stop = False

    def _emit_steered_echo(self, text: str) -> None:
        """Publish a steered interjection so frontends place it in the timeline.

        An idle prompt is echoed by the terminal itself, but a message folded
        into a running turn has no on-screen representation, so emit a
        ``UserMessage(steered=True)``. Echoing is best-effort: a display concern
        must never break the turn.
        """
        sink = self._event_sink
        if sink is None:
            return
        try:
            from ms_agent.ui.events import UserMessage
            sink.emit(UserMessage(text=text, steered=True))
        except Exception:  # noqa: BLE001
            pass

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        last = messages[-1]
        if last.tool_calls:
            # The assistant still has unresolved tool_calls: injecting a user
            # message here would break the assistant.tool_calls → tool pairing
            # required by OpenAI-compatible APIs. Never steer in this state.
            return
        if last.role in ('tool', 'user'):
            # Safe boundary — tool results are complete. Non-blocking steering:
            # fold in any queued plain messages and continue the same turn.
            self._inject_steering(runtime, messages)
            return

        release = getattr(runtime, 'release_skill_usage', None)
        if release is not None:
            release()
        turn = await self._session.run_turn(messages=messages, runtime=runtime)
        if turn.action == 'quit':
            runtime.should_stop = True
            return
        acquire = getattr(runtime, 'acquire_skill_usage', None)
        if acquire is not None:
            await acquire()
        runtime.should_stop = False
        if turn.action == 'resume_context':
            runtime.resume_pending_context()
            runtime.resume_context_requested = True
            return
        # A new instruction supersedes a paused request, but leaves its history.
        clear = getattr(runtime, 'clear_pending_context', None)
        if clear is not None:
            clear()
        messages.append(
            Message(
                role='user', content=turn.text, attachments=turn.attachments))
