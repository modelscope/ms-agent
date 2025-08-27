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

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role in ('tool', 'user'):
            return

        while True:
            query = input('>>> ').strip()
            if query:
                break

        if not query:
            runtime.should_stop = True
        else:
            runtime.should_stop = False
            messages.append(Message(role='user', content=query))
