# Copyright (c) Alibaba, Inc. and its affiliates.
from ms_agent.llm.modelscope_llm import ModelScope
from ms_agent.llm.openai_llm import OpenAI

all_services_mapping = {
    'modelscope': ModelScope,
    'openai': OpenAI,
}
