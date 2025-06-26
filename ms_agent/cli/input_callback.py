# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class InputCallback(Callback):
    """Waiting for human inputs."""

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.chat_finished = False

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role in ('tool',
                                                            'user'):  # noqa
            return

        query = input('>>>')
        if not query:
            self.chat_finished = True
        else:
            messages.append(Message(role='user', content=query))

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        runtime.should_stop = runtime.should_stop and self.chat_finished
