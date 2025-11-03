# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
from typing import List

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class AnalystCallback(Callback):
    """Save output plan to local disk.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.file_system = FileSystemTool(config)
        self.report_path = self.config.get(
            'report_path',
            os.path.join(self.config.output_dir, 'analysis_report.md'))

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        await self.file_system.connect()

        if os.path.exists(os.path.join(self.config.output_dir, 'plan.json')):
            plan = self.file_system.read_file(
                os.path.join(self.config.output_dir, 'plan.json'))
            if not plan:
                logger.error(
                    'The plan.json file is empty, please check the file.')
            user_message = Message(
                role='user',
                content=
                (f'The complete plan for the current financial analysis task is as follows:\n{plan}\n'
                 f'Please follow the plan to complete the data analysis task.\n'
                 f'IMPORTANT: Review the input analysis specification provided under "financial_data_dimension"'
                 ))
        else:
            user_message = Message(
                role='user',
                content=
                ('Please conduct data analysis in accordance with the research plan followed during the data '
                 'collection phase and the results obtained from data collection.'
                 ))
        messages.append(user_message)

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        for message in messages[::-1]:
            if message.role == 'assistant' and not message.tool_calls:
                with open(self.report_path, 'w') as f:
                    filtered_content = re.sub(
                        r'\s*\[ACT=(?:code|collect|report|fix)\]\s*', '',
                        message.content).strip()
                    f.write(filtered_content)
                break

        user_message = Message(
            role='user',
            content=json.dumps({'report_path': self.report_path},
                               ensure_ascii=False,
                               indent=2))
        messages.append(user_message)
