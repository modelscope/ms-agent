# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import uuid
from typing import List

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class SearcherCallback(Callback):
    """
    Callback for Searcher agent.

    Responsibilities:
    - on_task_begin: Clean up system prompt formatting
    - on_task_end: Save the final search result to file
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.output_dir = getattr(config, 'output_dir', './output')
        self.search_result_path = os.path.join(
            self.output_dir, f'search_result_{uuid.uuid4().hex[:4]}.json')

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """Clean up system prompt formatting."""
        for message in messages:
            if message.role == 'system':
                # Remove escaped newlines that might interfere with rendering
                message.content = message.content.replace('\\\n', '')
            elif message.role == 'user':
                try:
                    search_task_description = json.loads(message.content)
                    self.search_task_id = search_task_description.get(
                        'task_id') or search_task_description.get('任务ID')
                    if self.search_task_id:
                        self.search_result_path = os.path.join(
                            self.output_dir,
                            f'search_result_{self.search_task_id}.json')
                except json.JSONDecodeError:
                    logger.warning(
                        f'Failed to parse search task description: {message.content}'
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f'Unexpected error when parsing search task description: {message.content}, '
                        f'with error: {e}')
                    continue

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """
        Save the final search result to file.
        Supports JSON format with fallback to markdown.
        """
        if os.path.exists(self.search_result_path):
            logger.info(
                f'Search result already exists at {self.search_result_path}')
            return

        # Find the last assistant message without tool calls
        for message in reversed(messages):
            if message.role == 'assistant' and not message.tool_calls:
                content = message.content
                if not content:
                    continue

                # Try to save as JSON
                try:
                    parsed_json = json.loads(content)
                    with open(
                            self.search_result_path, 'w',
                            encoding='utf-8') as f:
                        json.dump(parsed_json, f, ensure_ascii=False, indent=2)
                    logger.info(
                        f'Searcher: Search result saved to {self.search_result_path}'
                    )
                except json.JSONDecodeError:
                    # Fallback to markdown if not valid JSON
                    logger.warning(
                        'Failed to parse search result as JSON, saving as markdown'
                    )
                    self.search_result_path = self.search_result_path.replace(
                        '.json', '.md')
                    with open(
                            self.search_result_path, 'w',
                            encoding='utf-8') as f:
                        f.write(content)
                    logger.info(
                        f'Searcher: Search result saved to {self.search_result_path}'
                    )
                except Exception as e:
                    logger.warning(
                        f'Unexpected error when saving search result: {e}')
                return

        logger.warning('Searcher: No final search result found in messages')
