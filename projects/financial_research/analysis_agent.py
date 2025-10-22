# Copyright (c) Alibaba, Inc. and its affiliates.
import logging

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.utils.constants import DEFAULT_TAG
from omegaconf import DictConfig

logger = logging.getLogger(__name__)


class AnalysisAgent(LLMAgent):
    """
    Analysis Agent with direct Python code execution capabilities.
    This agent extends LLMAgent with sophisticated data analysis tools that can
    execute Python code in a secure Docker sandbox with state persistence.

    Features:
    - Docker container isolation for security
    - State persistence across multiple code executions
    - Resource limits (CPU, memory)
    - Data directory mounting for file access
    """

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
