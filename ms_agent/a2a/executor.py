import logging
import os
import sys
from contextlib import contextmanager
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart
from a2a.utils import new_agent_text_message, new_task
from ms_agent.utils.logger import get_logger

from .errors import wrap_a2a_error
from .session_store import A2AAgentStore
from .translator import extract_text_from_a2a_message, ms_messages_to_text

logger = get_logger()


def configure_a2a_logging(log_file: str | None = None) -> None:
    """Set up logging for the A2A server process."""
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stderr)

    fmt = logging.Formatter(
        '%(asctime)s [%(name)s] %(levelname)s: %(message)s')
    handler.setFormatter(fmt)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


class MSAgentA2AExecutor(AgentExecutor):
    """A2A ``AgentExecutor`` backed by ms-agent's ``LLMAgent``.

    Each A2A task maps to an agent instance managed by ``A2AAgentStore``.
    The executor translates the incoming A2A message to a user query,
    runs the agent, and streams updates back through the event queue.
    """

    def __init__(
        self,
        config_path: str,
        trust_remote_code: bool = False,
        max_tasks: int = 8,
        task_timeout: int = 3600,
    ) -> None:
        self.config_path = config_path
        self.trust_remote_code = trust_remote_code
        self._store = A2AAgentStore(
            config_path=config_path,
            trust_remote_code=trust_remote_code,
            max_tasks=max_tasks,
            task_timeout=task_timeout,
        )

    @staticmethod
    @contextmanager
    def _suppress_stdout():
        """Redirect stdout to devnull while running agent logic.

        ``LLMAgent.step()`` writes streaming tokens to ``sys.stdout``,
        which would corrupt any stdio-based transport.
        """
        real_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
        try:
            yield
        finally:
            sys.stdout.close()
            sys.stdout = real_stdout

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute the agent's logic for an inbound A2A message."""
        user_text = context.get_user_input()
        if not user_text and context.message:
            user_text = extract_text_from_a2a_message(context.message)

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        try:
            await updater.update_status(TaskState.working)

            entry = await self._store.get_or_create(task.id)
            entry.is_running = True

            try:
                with self._suppress_stdout():
                    result = await entry.agent.run(user_text, stream=True)

                    if hasattr(result, '__aiter__'):
                        async for chunk in result:
                            entry.messages = chunk
                            if entry.cancelled:
                                await updater.cancel()
                                return
                    elif isinstance(result, list):
                        entry.messages = result

                response_text = ms_messages_to_text(entry.messages)
                if not response_text:
                    from .translator import collect_full_response
                    response_text = collect_full_response(entry.messages)

                if response_text:
                    await updater.add_artifact(
                        [Part(root=TextPart(text=response_text))],
                        name='response',
                    )
                    await updater.complete()
                else:
                    await updater.complete(
                        new_agent_text_message(
                            '(Agent completed with no text output)',
                            task.context_id,
                            task.id,
                        ))

            finally:
                entry.is_running = False

        except Exception as e:
            logger.error(
                'A2A execute error for task %s: %s', task.id, e, exc_info=True)
            err_info = wrap_a2a_error(e)
            try:
                await updater.failed(
                    new_agent_text_message(
                        f'Error: {err_info["message"]}',
                        task.context_id,
                        task.id,
                    ))
            except Exception:
                logger.warning('Failed to send error status', exc_info=True)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Cancel a running task."""
        task_id = context.task_id
        updater = TaskUpdater(
            event_queue,
            task_id,
            context.context_id,
        )

        entry = self._store.get(task_id) if task_id else None
        if entry:
            entry.request_cancel()

        await updater.cancel()
        logger.info('A2A task %s cancel requested', task_id)

    async def cleanup(self) -> None:
        """Shut down all agent instances."""
        await self._store.close_all()
