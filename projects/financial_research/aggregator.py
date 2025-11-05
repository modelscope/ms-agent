# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from tkinter import N
from typing import Any, AsyncGenerator, List, Union

import json
from callbacks.file_parser import extract_code_blocks
from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_TAG
from omegaconf import DictConfig

logger = get_logger()


class AggregatorAgent(LLMAgent):
    """
    Aggregator Agent that aggregates the reports from SearchAgent and CollectorAgent.
    """

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

    async def run(
            self, inputs: Union[str, List[str], List[Message],
                                List[List[Message]]], **kwargs
    ) -> Union[List[Message], AsyncGenerator[List[Message], Any]]:
        reports = []  # List of reports

        if isinstance(inputs, list):
            if isinstance(inputs[0], str):
                refractory_inputs = [[Message(role='user', content=item)]
                                     for item in inputs]
            elif isinstance(inputs[0], Message):
                refractory_inputs = [inputs]
            elif len(inputs) > 1 and isinstance(inputs[0], list):
                refractory_inputs = inputs
            else:
                raise ValueError(
                    f"Invalid input type: List[{type(inputs[0]) if inputs else 'empty list'}]"
                )
        elif isinstance(inputs, str):
            refractory_inputs = [[Message(role='assistant', content=inputs)]]
        else:
            raise ValueError(f'Invalid input type: {type(inputs)}')

        for sub_inputs in refractory_inputs:
            report = None
            for message in sub_inputs[::-1]:
                if message.role == 'user':
                    report_path = json.loads(message.content).get(
                        'report_path', '')
                    if not report_path:
                        report_path = extract_code_blocks(
                            message.content)[0][0].get('code').get(
                                'report_path', '')
                    break

            if report_path and os.path.exists(report_path):
                with open(report_path, 'r') as f:
                    report = f.read()

            if not report:
                reports.append(message.content)
            else:
                reports.append(report)
        reports_content = '\n'.join(reports)

        plan = {}
        plan_path = os.path.join(self.config.output_dir, 'plan.json')
        if os.path.exists(plan_path):
            try:
                with open(plan_path, 'r') as f:
                    content = f.read().strip()
                    if content:  # Only load if file is not empty
                        plan.update(json.loads(content))
            except Exception as e:
                logger.warning(
                    f'Failed to load plan.json: {e}. Using empty plan.')
        plan = json.dumps(plan, ensure_ascii=False, indent=2)

        return await super().run(
            messages=
            (f'The reports from the SearchAgent and AnalystAgent are as follows:\n{reports_content}\n'
             f'Please integrate the reports into a comprehensive financial analysis report.\n'
             f'Please review the original plan for the financial analysis task:\n{plan}\n'
             ),
            kwargs=kwargs)
