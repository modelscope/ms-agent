# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import shutil
from copy import deepcopy
from typing import List

from ms_agent import LLMAgent
from ms_agent.llm import LLM, Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class GenerateScript(LLMAgent):

    def __init__(self,
                 config: DictConfig,
                 tag: str,
                 trust_remote_code: bool = False,
                 **kwargs):
        super().__init__(config, tag, trust_remote_code, **kwargs)
        self.work_dir = getattr(self.config, 'output_dir', 'output')
        extra = getattr(self.config, 'extra_requirement', '')
        if extra is None:
            extra = ''
        self.extra_req = extra
        os.makedirs(self.work_dir, exist_ok=True)

    def prepare_llm(self):
        """Initialize the LLM model from the configuration."""
        config = deepcopy(self.config)
        config.generation_config.temperature = 0.6
        config.generation_config.top_k = 50
        self.llm: LLM = LLM.from_config(self.config)

    def on_task_end(self, messages: List[Message]):
        script = os.path.join(self.work_dir, 'script.txt')
        title = os.path.join(self.work_dir, 'title.txt')

        if not os.path.isfile(script) or not os.path.isfile(title):
            for root, dirs, files in os.walk(self.work_dir):
                if 'script.txt' in files and 'title.txt' in files:
                    if root != self.work_dir:
                        logger.info(
                            f'Found files in subdirectory {root}, moving to {self.work_dir}'
                        )
                        for filename in os.listdir(root):
                            if filename in ['script.txt', 'title.txt']:
                                src = os.path.join(root, filename)
                                dst = os.path.join(self.work_dir, filename)
                                if os.path.isfile(src):
                                    shutil.move(src, dst)
                    break

        if not os.path.isfile(script) or not os.path.isfile(title):
            assistant_texts = []
            try:
                for m in messages:
                    if getattr(m, 'role', '') == 'assistant' and getattr(
                            m, 'content', None):
                        assistant_texts.append(m.content)
            except Exception:
                assistant_texts = []

            combined = '\n\n'.join(assistant_texts).strip()

            # Filter out conversational fillers to keep only the script content.
            lines = combined.splitlines()
            cleaned_lines = []
            filler_patterns = [
                r'^(sure|okay|here is|i will|let me|i have created|creating|based on).{0,50}:?$',
                r'^title:?\s*',
                r'^script:?\s*',
            ]

            for line in lines:
                is_filler = False
                for pat in filler_patterns:
                    if re.match(pat, line.strip(), re.IGNORECASE):
                        is_filler = True
                        break
                if not is_filler:
                    cleaned_lines.append(line)

            combined = '\n'.join(cleaned_lines).strip()
            # ----------------------------------------------------

            if combined:
                if not os.path.isfile(script):
                    try:
                        with open(script, 'w', encoding='utf-8') as f:
                            f.write(combined)
                        logger.warning(
                            'script.txt missing - created fallback from assistant output.'
                        )
                    except Exception as e:
                        logger.error(
                            f'Failed to write fallback script.txt: {e}')
                if not os.path.isfile(title):
                    # Use first non-empty line as title, fallback to prefix
                    first_line = ''
                    for line in combined.splitlines():
                        if line.strip():
                            first_line = line.strip()
                            break
                    if not first_line:
                        first_line = (
                            combined[:60]
                            + '...') if len(combined) > 60 else combined
                    try:
                        with open(title, 'w', encoding='utf-8') as f:
                            f.write(first_line)
                        logger.warning(
                            'title.txt missing — created fallback from assistant output.'
                        )
                    except Exception as e:
                        logger.error(
                            f'Failed to write fallback title.txt: {e}')
            else:
                pass

        assert os.path.isfile(script)
        assert os.path.isfile(title)
        return super().on_task_end(messages)

    async def run(self, query: str, **kwargs):
        query += self.extra_req
        messages = [
            Message(role='system', content=self.system),
            Message(role='user', content=query),
        ]
        inputs = await super().run(messages, **kwargs)
        with open(os.path.join(self.work_dir, 'topic.txt'), 'w') as f:
            f.write(messages[1].content)
        return inputs
