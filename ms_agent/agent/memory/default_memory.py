# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from copy import deepcopy
from functools import partial, wraps
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from ms_agent.agent.memory import Memory
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import logger
from ms_agent.utils.prompts import FACT_RETRIEVAL_PROMPT
from omegaconf import DictConfig, OmegaConf


class DefaultMemory(Memory):
    """The memory refine tool"""

    def __init__(self,
                 config: DictConfig,
                 cache_messages: Optional[List[Message]] = None,
                 conversation_id: Optional[str] = None,
                 persist: bool = True,
                 path: str = None,
                 history_mode: Literal['add', 'overwrite'] = 'add',
                 current_memory_cache_position: int = 0):
        super().__init__(config)
        cache_messages = [message.to_dict() for message in cache_messages
                          ] if cache_messages else []
        self.cache_messages = cache_messages
        self.conversation_id: Optional[str] = conversation_id or getattr(
            config.memory, 'conversation_id', None)
        self.persist: Optional[bool] = persist or getattr(
            config.memory, 'persist', True)
        self.compress: Optional[bool] = getattr(config.memory, 'compress',
                                                True)
        self.is_retrieve: Optional[bool] = getattr(config.memory,
                                                   'is_retrieve', True)
        self.path: Optional[str] = path or getattr(
            config.memory, 'path', None) or getattr(self.config, 'output_dir',
                                                    'output')
        self.history_mode = history_mode or getattr(config.memory,
                                                    'history_mode')
        self.ignore_role: List[str] = getattr(config.memory, 'ignore_role',
                                              ['tool', 'system'])
        self.ignore_fields: List[str] = getattr(config.memory, 'ignore_fields',
                                                ['reasoning_content'])
        self.current_memory_cache_position = current_memory_cache_position
        self.memory = self._init_memory()

    def _should_update_memory(self, messages: List[Message]) -> bool:
        # TODO: Avoid unnecessary frequent updates and reduce the number of update operations
        return True

    def _find_messages_common_prefix(
        self,
        messages: List[Dict],
        ignore_role: Optional[Set[str]] = {'system'},
        ignore_fields: Optional[Set[str]] = {'reasoning_content'},
    ) -> Tuple[List[Dict], int, int]:
        """
        Compare the differences between messages and cached messages, and extract the longest common prefix.

        Args:
            messages: Current list of message dictionaries in OpenAI API format.
            ignore_role: Whether to ignore messages with role="system" or role="tool".
            ignore_fields: Optional set of field names to exclude from comparison, e.g., {"reasoning_content"}.

        Returns:
            The longest common prefix as a list of dictionaries.
        """
        if not messages or not isinstance(messages, list):
            return [], -1, -1

        if ignore_fields is None:
            ignore_fields = set()

        # Preprocessing: filter messages based on ignore_role
        def _ignore_role(msgs):
            filtered = []
            indices = [
            ]  # The original index corresponding to each filtered message
            for idx, msg in enumerate(msgs):
                if ignore_role and getattr(msg, 'role') in ignore_role:
                    continue
                filtered.append(msg)
                indices.append(idx)
            return filtered, indices

        filtered_messages, indices = _ignore_role(messages)
        filtered_cache_messages, cache_indices = _ignore_role(
            self.cache_messages)

        # Find the shortest length to avoid out-of-bounds access
        min_length = min(
            len(msgs) for msgs in [filtered_messages, filtered_cache_messages])
        common_prefix = []

        idx = 0
        for idx in range(min_length):
            current_cache_msg = filtered_cache_messages[idx]
            current_msg = filtered_messages[idx]
            is_common = True

            # Compare other fields except the ignored ones
            all_keys = ['role', 'content', 'reasoning_content', 'tool_calls']
            for key in all_keys:
                if key in ignore_fields:
                    continue
                if getattr(current_cache_msg, key, '') != getattr(
                        current_msg, key, ''):
                    is_common = False
                    break

            if not is_common:
                break

            # Add a deep copy of the current message to the result (preserve original structure)
            common_prefix.append(deepcopy(current_msg))

        if len(common_prefix) == 0:
            return [], -1, -1

        return common_prefix, indices[idx], cache_indices[idx]

    def rollback(self, common_prefix_messages, cache_message_idx):
        # Support retry mechanism: roll back memory to the idx-th message in self.cache_messages
        if self.history_mode == 'add':
            # Only overwrite update mode supports rollback; rollback involves deletion
            return
        # TODO: Implement actual rollback logic
        self.memory.delete_all(user_id=self.conversation_id)
        self.memory.add(common_prefix_messages, user_id=self.conversation_id)

    def add(self, messages: List[Message]) -> None:
        messages_dict = []
        for message in messages:
            if isinstance(message, Message):
                messages_dict.append(message.to_dict())
            else:
                messages_dict.append(message)
        self.memory.add(messages_dict, user_id=self.conversation_id)
        self.cache_messages.extend(messages_dict)
        res = self.memory.get_all(user_id=self.conversation_id)
        logger.info(
            f'Add memory done, current memory infos: {"; ".join([item["memory"] for item in res["results"]])}'
        )

    def search(self, query: str) -> str:
        relevant_memories = self.memory.search(
            query, user_id=self.conversation_id, limit=3)
        memories_str = '\n'.join(f"- {entry['memory']}"
                                 for entry in relevant_memories['results'])
        return memories_str

    async def run(self, messages, ignore_role=None, ignore_fields=None):
        if not self.is_retrieve or not self._should_update_memory(messages):
            return messages

        common_prefix_messages, messages_idx, cache_message_idx \
            = self._find_messages_common_prefix(messages,
                                                ignore_role=ignore_role,
                                                ignore_fields=ignore_fields)
        if self.history_mode == 'overwrite':
            if cache_message_idx < len(self.cache_messages):
                self.rollback(common_prefix_messages, cache_message_idx)
            self.add(messages[max(messages_idx, 0):])
        else:
            self.add(messages)

        query = getattr(messages[-1], 'content')
        memories_str = self.search(query)
        # Remove the messages section corresponding to memory, and add the related memory_str information
        if getattr(messages[0], 'role') == 'system':
            system_prompt = getattr(
                messages[0], 'content') + f'\nUser Memories: {memories_str}'
        else:
            system_prompt = f'\nYou are a helpful assistant. Answer the question based on query and memories.\n' \
                            f'User Memories: {memories_str}'
        new_messages = [Message(role='system', content=system_prompt)
                        ] + messages[messages_idx:]
        return new_messages

    def _init_memory(self):
        import mem0
        parse_messages_origin = mem0.memory.main.parse_messages

        @wraps(parse_messages_origin)
        def patched_parse_messages(messages, ignore_role):
            response = ''
            for msg in messages:
                if 'system' not in ignore_role and msg['role'] == 'system':
                    response += f"system: {msg['content']}\n"
                if msg['role'] == 'user':
                    response += f"user: {msg['content']}\n"
                if msg['role'] == 'assistant' and msg['content'] is not None:
                    response += f"assistant: {msg['content']}\n"
                if 'tool' not in ignore_role and msg['role'] == 'tool':
                    response += f"tool: {msg['content']}\n"
            return response

        patched_func = partial(
            patched_parse_messages,
            ignore_role=self.ignore_role,
        )

        mem0.memory.main.parse_messages = patched_func

        if not self.is_retrieve:
            return

        embedder: Optional[str] = getattr(
            self.config.memory, 'embedder',
            OmegaConf.create({
                'provider': 'openai',
                'config': {
                    'api_key': os.getenv('DASHSCOPE_API_KEY'),
                    'openai_base_url':
                    'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    'model': 'text-embedding-v4',
                }
            }))

        llm = {}
        if self.compress:
            llm_config = getattr(self.config.memory, 'llm', None)
            if llm_config is not None:
                # follow mem0 config
                model = llm_config.get('model')
                provider = llm_config.get('provider', 'openai')
                openai_base_url = llm_config.get('openai_base_url', None)
                openai_api_key = llm_config.get('api_key', None)
            else:
                llm_config = self.config.llm
                model = llm_config.model
                service = llm_config.service
                openai_base_url = getattr(llm_config, f'{service}_base_url',
                                          None)
                openai_api_key = getattr(llm_config, f'{service}_api_key',
                                         None)
                provider = 'openai'
            llm = {
                'provider': provider,
                'config': {
                    'model': model,
                    'openai_base_url': openai_base_url,
                    'api_key': openai_api_key
                }
            }

        mem0_config = {
            'is_infer': self.compress,
            'llm': llm,
            'vector_store': {
                'provider': 'qdrant',
                'config': {
                    'path': self.path,
                    'on_disk': self.persist
                }
            },
            'embedder': embedder
        }
        logger.info(f'Memory config: {mem0_config}')
        # Prompt content is too long, default logging reduces readability
        mem0_config['custom_fact_extraction_prompt'] = getattr(
            self.config.memory, 'fact_retrieval_prompt', FACT_RETRIEVAL_PROMPT)
        memory = mem0.Memory.from_config(mem0_config)
        if self.cache_messages:
            memory.add(self.cache_messages, user_id=self.conversation_id)
        return memory
