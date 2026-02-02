# Copyright (c) ModelScope Contributors. All rights reserved.
from typing import List

from file_parser import extract_code_blocks
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class OrchestratorCallback(Callback):
    """Save output plan to local disk.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.file_system = FileSystemTool(config)

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        await self.file_system.connect()

        for message in messages:
            if message.role == 'system':
                message.content = message.content.replace('\\\n', '')

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        if messages[-1].tool_calls or messages[-1].role == 'tool':
            return

        await self.file_system.create_directory()
        content = '\n'.join([m.content for m in messages[2:]])
        all_files, _ = extract_code_blocks(content)
        results = []
        for f in all_files:
            result = await self.file_system.write_file(f['filename'],
                                                       f['code'])
            results.append(result)

        r = '\n'.join(results)
        if len(r) > 0:
            messages.append(Message(role='user', content=r))
