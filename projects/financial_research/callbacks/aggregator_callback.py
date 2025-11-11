# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
from typing import List

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class AggregatorCallback(Callback):
    """Save output plan to local disk.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.file_system = FileSystemTool(config)
        self.report_path = os.path.join(self.config.output_dir,
                                        'aggregator_report.md')

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        await self.file_system.connect()

        for message in messages:
            if message.role == 'system':
                message.content = message.content.replace('\\\n', '')

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        for message in messages[::-1]:
            if message.role == 'assistant' and not message.tool_calls:
                with open(self.report_path, 'w') as f:
                    filtered_content = re.sub(
                        r'\s*\[ACT=(?:outline|partial_report|final_report)\]\s*:?\s*.*?(?:\n|\.)',
                        '',
                        message.content,
                        flags=re.MULTILINE).strip()
                    f.write(filtered_content)
                break
        logger.info(f'Aggregator report saved to {self.report_path}')
