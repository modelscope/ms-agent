# Copyright (c) Alibaba, Inc. and its affiliates.
from copy import deepcopy
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from langchain.chains.question_answering.map_reduce_prompt import messages
from mem0 import Memory as Mem0Memory
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
                 persist: bool = False,
                 path: str = None,
                 history_mode: Literal['add', 'overwrite'] = 'add',
                 current_memory_cache_position: int = 0):
        super().__init__(config)
        cache_messages = [message.to_dict() for message in cache_messages] if cache_messages else []
        self.cache_messages = cache_messages
        self.conversation_id: Optional[str] = conversation_id or getattr(
            config.memory, 'conversation_id', None)
        self.persist: Optional[bool] = persist or getattr(
            config.memory, 'persist', None)
        self.compress: Optional[bool] = getattr(config.memory, 'compress',
                                                None)
        self.embedder: Optional[str] = getattr(config.memory, 'embedder', None)
        self.is_retrieve: Optional[bool] = getattr(config.memory,
                                                   'is_retrieve', None)
        self.path: Optional[str] = path or getattr(config.memory, 'path', None) or getattr(self.config, 'output_dir', 'output')
        print(f'path: {self.path}')
        self.history_mode = history_mode or getattr(config.memory,
                                                    'history_mode', None)
        self.current_memory_cache_position = current_memory_cache_position
        self.memory = self._init_memory()

    def _should_update_memory(self, messages: List[Message]) -> bool:
        return True

    def _find_messages_common_prefix(
        self,
        messages: List[Dict],
        ignore_role: Optional[Set[str]] = {'system'},
        ignore_fields: Optional[Set[str]] = {'reasoning_content'},
    ) -> Tuple[List[Dict], int, int]:
        """
        比对 messages 和缓存messages的差异，并提取最长公共前缀。

        Args:
            messages: 本次 List[Dict]，符合 OpenAI API 格式
            ignore_role: 是否忽略 role="system"、或者role="tool" 的message
            ignore_fields: 可选，要忽略比较的字段名集合，如 {"reasoning_content"}

        Returns:
            最长公共前缀（List[Dict]）
        """
        if not messages or not isinstance(messages, list):
            return [], -1, -1

        if ignore_fields is None:
            ignore_fields = set()

        # 预处理：根据 ignore_role 过滤消息
        def _ignore_role(msgs):
            filtered = []
            indices = []  # 每个 filtered 消息对应的原始索引
            for idx, msg in enumerate(msgs):
                if ignore_role and getattr(msg, 'role') in ignore_role:
                    continue
                filtered.append(msg)
                indices.append(idx)
            return filtered, indices

        filtered_messages, indices = _ignore_role(messages)
        filtered_cache_messages, cache_indices = _ignore_role(
            self.cache_messages)

        # 找最短长度，避免越界
        min_length = min(
            len(msgs) for msgs in [filtered_messages, filtered_cache_messages])
        common_prefix = []

        idx = 0
        for idx in range(min_length):
            current_cache_msg = filtered_cache_messages[idx]
            current_msg = filtered_messages[idx]
            is_common = True

            # 比较其他字段（除了忽略的字段）
            all_keys = ['role', 'content', 'reasoning_content', 'tool_calls']
            for key in all_keys:
                if key in ignore_fields:
                    continue
                if getattr(current_cache_msg, key, '') != getattr(current_msg, key, ''):
                    is_common = False
                    break

            if not is_common:
                break

            # 添加当前消息的深拷贝到结果中（保留原始结构）
            common_prefix.append(deepcopy(current_msg))

        if len(common_prefix) == 0:
            return [], -1, -1

        return common_prefix, indices[idx], cache_indices[idx]

    def rollback(self, common_prefix_messages, cache_message_idx):
        # 支持retry机制，将memory回退到 self.cache_messages的第idx 条message
        if self.history_mode == 'add':
            # 只有覆盖更新模式才支持回退；回退涉及删除
            return
        # TODO: 真正的回退
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
        logger.info(f'Add memory done, current memory infos: {"; ".join([item["memory"] for item in res["results"]])}')

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
        # 将memory对应的messages段删除，并添加相关的memory_str信息
        if getattr(messages[0], 'role') == 'system':
            system_prompt = getattr(messages[0],
                                'content') + f'\nUser Memories: {memories_str}'
        else:
            system_prompt = f'\nYou are a helpful assistant. Answer the question based on query and memories.\nUser Memories: {memories_str}'
        new_messages = [Message(role='system', content=system_prompt)] + messages[messages_idx:]
        return new_messages

    def _init_memory(self) -> Mem0Memory | None:
        if not self.is_retrieve:
            return

        if self.embedder is None:
            # TODO: set default
            raise ValueError('embedder must be set when is_retrieve=True.')
        embedder = self.embedder

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
                provider = llm_config.service
                openai_base_url = getattr(llm_config, f'{provider}_base_url',
                                          None)
                openai_api_key = getattr(llm_config, f'{provider}_api_key',
                                         None)

            llm = {
                'provider': provider,
                'config': {
                    'model': model,
                    'openai_base_url': openai_base_url,
                    'api_key': openai_api_key
                }
            }

        mem0_config = {
            'is_infer':
            self.compress,
            'llm':
            llm,
            'custom_fact_extraction_prompt':
            getattr(self.config.memory, 'fact_retrieval_prompt',
                    FACT_RETRIEVAL_PROMPT),
            'vector_store': {
                'provider': 'qdrant',
                'config': {
                    'path': self.path,
                    # "on_disk": self.persist
                    'on_disk': True
                }
            },
            'embedder':
            embedder
        }
        logger.info(f'Memory config: {mem0_config}')
        memory = Mem0Memory.from_config(mem0_config)
        if self.cache_messages:
            memory.add(self.cache_messages, user_id=self.conversation_id)
        return memory


async def main():
    import os
    import json
    cfg = {
        'memory': {
            'conversation_id': 'default_id',
            'persist': True,
            'compress': True,
            'is_retrieve': True,
            'history_mode': 'add',
            'llm': {
                'provider': 'openai',
                'model': 'qwen3-235b-a22b-instruct-2507',
                'openai_base_url':
                'https://dashscope.aliyuncs.com/compatible-mode/v1',
                'api_key': os.getenv('DASHSCOPE_API_KEY'),
            },
            'embedder': {
                'provider': 'openai',
                'config': {
                    'api_key': os.getenv('DASHSCOPE_API_KEY'),
                    'openai_base_url':
                    'https://dashscope.aliyuncs.com/compatible-mode/v1',
                    'model': 'text-embedding-v4',
                }
            }
        }
    }
    with open('openai_format_test_case1.json', 'r') as f:
        data = json.load(f)
    config = OmegaConf.create(cfg)
    memory = DefaultMemory(
        config, path='./output', cache_messages=None, history_mode='add')
    res = await memory.run(messages=[Message({
        'role': 'user',
        'content': '使用bun会对新项目的影响大吗，有哪些新特性'
    })])
    print(res)


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
