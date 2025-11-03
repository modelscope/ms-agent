import os
from typing import List, Union

import json
from callbacks.file_parser import extract_code_blocks
from ms_agent.agent.code_agent import CodeAgent
from ms_agent.llm import Message
from ms_agent.llm.openai import OpenAIChat
from ms_agent.tools.search_engine import get_web_search_tool
from ms_agent.utils import get_logger
from ms_agent.workflow.deep_research.research_workflow_beta import \
    ResearchWorkflowBeta
from omegaconf import DictConfig

logger = get_logger()


class SearchAgent(CodeAgent):
    """Agent wrapper that delegates work to ResearchWorkflowBeta."""

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)

        if isinstance(self.config, DictConfig):
            if hasattr(self.config, 'llm'):
                llm_config = self.config.llm
                api_key = getattr(llm_config, 'openai_api_key',
                                  '') or os.getenv('OPENAI_API_KEY')
                base_url = getattr(llm_config, 'openai_base_url',
                                   '') or os.getenv('OPENAI_BASE_URL')
                model = getattr(llm_config, 'model',
                                '') or 'Qwen/Qwen3-235B-A22B-Instruct-2507'
                self.chat_client = OpenAIChat(
                    api_key=api_key, base_url=base_url, model=model)
            else:
                raise ValueError(
                    'LLM configuration not found, SearchAgent requires OpenAI compatible API.'
                )

            if hasattr(self.config, 'tools') and hasattr(
                    self.config.tools, 'search_engine'):
                self.search_engine = get_web_search_tool(
                    config_file=getattr(self.config.tools.search_engine,
                                        'config_file', ''))
            else:
                raise ValueError('Search engine configuration not found.')

            self.workdir = getattr(self.config, 'output_dir',
                                   './output/research')

    async def run(self, inputs: Union[str, List[Message]],
                  **kwargs) -> List[Message]:
        workflow = ResearchWorkflowBeta(
            client=self.chat_client,
            search_engine=self.search_engine,
            workdir=self.workdir,
            use_ray=False,
            enable_multimodal=False)

        if inputs is None:
            return [Message(role='assistant', content='')]

        if isinstance(inputs, list):
            # Find the last assistant message with JSON content
            instruction = {}
            for message in inputs[::-1]:
                if message.role == 'assistant':
                    instruction = json.loads(
                        extract_code_blocks(message.content)[0][0].get(
                            'code', {}))
                    break

            if not instruction and os.path.exists(
                    os.path.join(self.workdir, 'plan.json')):
                with open(os.path.join(self.workdir, 'plan.json'), 'r') as f:
                    instruction = json.load(f)

            user_prompt = json.dumps(
                {
                    'public_sentiment_dimension':
                    instruction.get('public_sentiment_dimension', {}),
                },
                ensure_ascii=False,
                indent=2)
        elif isinstance(inputs, str):
            user_prompt = inputs
        else:
            raise ValueError(
                'Invalid input type, SearchAgent requires a string or list of messages.'
            )

        report_path = await workflow.run(
            user_prompt=user_prompt,
            breadth=getattr(self.config, 'breadth', 4),
            depth=getattr(self.config, 'depth', 2),
            is_report=getattr(self.config, 'is_report', True),
        )

        result_content = report_path if report_path else 'No report generated.'
        result_content = json.dumps({'report_path': report_path},
                                    ensure_ascii=False,
                                    indent=2)
        return [Message(role='user', content=result_content)]
