# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from typing import Any, AsyncGenerator, List, Union

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_TAG
from omegaconf import DictConfig

logger = get_logger()


class ReporterAgent(LLMAgent):
    """
    Reporter Agent that generates structured reports based on evidence.

    This agent is designed to work with the ReportTool to:
    1. Generate report outlines with evidence bindings
    2. Prepare chapter bundles with full evidence content
    3. Write chapters with proper citations
    4. Track and resolve evidence conflicts
    5. Assemble final reports
    """

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

        # Reporter-specific configuration
        self._reports_dir = 'reports'
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'report_generator'):
            report_cfg = config.tools.report_generator
            self._reports_dir = getattr(report_cfg, 'reports_dir', 'reports')

    async def run(
            self, inputs: Union[str, List[str], List[Message],
                                List[List[Message]]], **kwargs
    ) -> Union[List[Message], AsyncGenerator[List[Message], Any]]:
        # Add context about the reporter's role
        if isinstance(inputs, str):
            # Enhance the input with context if needed
            enhanced_input = inputs

            # Check if evidence directory exists
            evidence_dir = os.path.join(self.output_dir, 'evidence')
            if os.path.exists(evidence_dir):
                evidence_index = os.path.join(evidence_dir, 'index.json')
                if os.path.exists(evidence_index):
                    logger.info(
                        f'ReporterAgent: Evidence index found at {evidence_index}'
                    )

            inputs = enhanced_input

        # Call parent run method
        return await super().run(inputs, **kwargs)
