# Copyright (c) Alibaba, Inc. and its affiliates.
from ms_agent.llm.anthropic_llm import Anthropic
from ms_agent.llm.dashscope_llm import DashScope
from ms_agent.llm.modelscope_llm import ModelScope
from ms_agent.llm.openai_llm import OpenAI

all_services_mapping = {
    'modelscope': ModelScope,
    'openai': OpenAI,
    'anthropic': Anthropic,
    'dashscope': DashScope,
}
