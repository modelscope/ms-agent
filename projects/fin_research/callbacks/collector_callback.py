# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from typing import List

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class CollectorCallback(Callback):
    """Save output plan to local disk.
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        for message in messages:
            if message.role == 'system':
                message.content = message.content.replace('\\\n', '')

        if os.path.exists(os.path.join(self.config.output_dir, 'plan.json')):
            with open(os.path.join(self.config.output_dir, 'plan.json'),
                      'r') as f:
                plan = json.load(f)
            if not plan:
                logger.error(
                    'The plan.json file is empty, please check the file.')
            if messages[-1].role == 'user':
                messages[-1].content += (
                    f'The complete plan for the current overall financial analysis task is as follows:\n{plan}\n'
                    f'Please follow the plan to complete the data collection task.\n'
                )
            elif messages[-1].role in ('assistant', 'tool', 'system'):
                user_message = Message(
                    role='user',
                    content=
                    (f'The complete plan for the current global financial analysis task is as follows:\n{plan}\n'
                     f'Please follow the plan to complete the data collection task.\n'
                     ))
                messages.append(user_message)
        else:
            user_message = Message(
                role='user',
                content=
                ('Please conduct data collection in accordance with the research plan '
                 'provided in orchestrator\'s output.'))
            messages.append(user_message)
