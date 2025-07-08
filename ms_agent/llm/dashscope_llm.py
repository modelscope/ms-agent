# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import List

from ms_agent.llm.openai_llm import OpenAI
from ms_agent.llm.utils import Message, Tool
from omegaconf import DictConfig


class DashScope(OpenAI):

    def __init__(self, config: DictConfig):
        super().__init__(
            config,
            base_url=config.llm.dashscope_base_url,
            api_key=config.llm.dashscope_api_key)

    def _call_llm_for_continue_gen(self,
                                   messages: List[Message],
                                   new_message,
                                   tools: List[Tool] = None,
                                   **kwargs):
        # ref: https://bailian.console.aliyun.com/?tab=doc#/doc/?type=model&url=https%3A%2F%2Fhelp.aliyun.com%2Fdocument_detail%2F2862210.html&renderType=iframe # noqa
        if messages and messages[-1].to_dict().get('partial', False):

            messages[-1].reasoning_content += new_message.reasoning_content
            messages[-1].content += new_message.content
            if new_message.tool_calls:
                if messages[-1].tool_calls:
                    messages[-1].tool_calls += new_message.tool_calls
                else:
                    messages[-1].tool_calls = new_message.tool_calls
        else:
            messages.append(new_message)
            messages[-1].partial = True

        messages = self.format_input_message(messages)
        return self._call_llm(messages=messages, tools=tools, **kwargs)
