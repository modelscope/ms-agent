# Copyright (c) Alibaba, Inc. and its affiliates.
import hashlib
import os
from copy import deepcopy
from functools import partial, wraps
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

import json
import json5
from ms_agent.agent.memory import Memory
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import logger
from ms_agent.utils.prompts import get_fact_retrieval_prompt
from omegaconf import DictConfig, OmegaConf


class MemoryMapping:
    memory_id: str = None
    memory: str = None
    valid: bool = None
    enable_idxs: List[int] = []
    disable_idx: int = -1

    def __init__(self, memory_id: str, value: str, enable_idxs: int
                 or List[int]):
        self.memory_id = memory_id
        self.value = value
        self.valid = True
        if isinstance(enable_idxs, int):
            enable_idxs = [enable_idxs]
        self.enable_idxs = enable_idxs

    def udpate_idxs(self, enable_idxs: int or List[int]):
        if isinstance(enable_idxs, int):
            enable_idxs = [enable_idxs]
        self.enable_idxs.extend(enable_idxs)

    def disable(self, disable_idx: int):
        self.valid = False
        self.disable_idx = disable_idx

    def try_enable(self, expired_disable_idx: int):
        if expired_disable_idx == self.disable_idx:
            self.valid = True
            self.disable_idx = -1

    def get(self):
        return self.value

    def to_dict(self) -> Dict:
        return {
            'memory_id': self.memory_id,
            'value': self.value,
            'valid': self.valid,
            'enable_idxs': self.enable_idxs.copy(
            ),  # Return a copy to prevent external modification
            'disable_idx': self.disable_idx
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryMapping':
        instance = cls(
            memory_id=data['memory_id'],
            value=data['value'],
            enable_idxs=data['enable_idxs'])
        instance.valid = data['valid']
        instance.disable_idx = data.get('disable_idx',
                                        -1)  # Compatible with old data
        return instance


class DefaultMemory(Memory):
    """The memory refine tool"""

    def __init__(self,
                 config: DictConfig,
                 conversation_id: Optional[str] = None,
                 persist: bool = True,
                 path: str = None,
                 history_mode: Literal['add', 'overwrite'] = None):
        super().__init__(config)
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
                                                    'history_mode', 'add')
        self.ignore_role: List[str] = getattr(config.memory, 'ignore_role',
                                              ['tool', 'system'])
        self.ignore_fields: List[str] = getattr(config.memory, 'ignore_fields',
                                                ['reasoning_content'])
        self.memory = self._init_memory_obj()
        self.init_cache_messages()

    def init_cache_messages(self):
        self.load_cache()
        if len(self.cache_messages) and not len(self.memory_snapshot):
            new_blocks = self._split_into_blocks(self.cache_messages)
            for messages in new_blocks:
                self.max_msg_id += 1
                self.add(messages, msg_id=self.max_msg_id)

    def save_cache(self):
        """
        Save self.max_msg_id, self.cache_messages, and self.memory_snapshot to self.path/cache_messages.json
        """
        cache_file = os.path.join(self.path, 'cache_messages.json')

        # Ensure the directory exists
        os.makedirs(self.path, exist_ok=True)

        data = {
            'max_msg_id': self.max_msg_id,
            'cache_messages': {
                str(k): ([msg.to_dict() for msg in msg_list], _hash)
                for k, (msg_list, _hash) in self.cache_messages.items()
            },
            'memory_snapshot': [mm.to_dict() for mm in self.memory_snapshot]
        }

        with open(cache_file, 'w', encoding='utf-8') as f:
            json5.dump(data, f, indent=2, ensure_ascii=False)

    def load_cache(self):
        """
        Load data from self.path/cache_messages.json into self.max_msg_id, self.cache_messages, and self.memory_snapshot
        """
        cache_file = os.path.join(self.path, 'cache_messages.json')

        if not os.path.exists(cache_file):
            # If the file does not exist, initialize default values and return.
            self.max_msg_id = -1
            self.cache_messages = {}
            self.memory_snapshot = []
            return

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json5.load(f)

            self.max_msg_id = data.get('max_msg_id', -1)

            # Parse cache_messages
            cache_messages = {}
            raw_cache_msgs = data.get('cache_messages', {})
            for k, (msg_list, timestamp) in raw_cache_msgs.items():
                msg_objs = [Message(**msg_dict) for msg_dict in msg_list]
                cache_messages[int(k)] = (msg_objs, timestamp)
            self.cache_messages = cache_messages

            # Parse memory_snapshot
            self.memory_snapshot = [
                MemoryMapping.from_dict(d)
                for d in data.get('memory_snapshot', [])
            ]

        except (json.JSONDecodeError, KeyError, Exception) as e:
            logger.warning(f'Failed to load cache: {e}')
            # Fall back to default state when an error occurs
            self.max_msg_id = -1
            self.cache_messages = {}
            self.memory_snapshot = []

    def delete_single(self, msg_id: int):
        messages_to_delete = self.cache_messages.get(msg_id, None)
        if messages_to_delete is None:
            return
        self.cache_messages.pop(msg_id, None)
        if msg_id == self.max_msg_id:
            self.max_msg_id = max(self.cache_messages.keys())

        idx = 0
        while idx < len(self.memory_snapshot):

            enable_ids = self.memory_snapshot[idx].enable_idxs
            disable_id = self.memory_snapshot[idx].disable_idx
            if msg_id == disable_id:
                self.memory_snapshot[idx].try_enable(msg_id)
                self.memory._create_memory(
                    data=self.memory_snapshot[idx].value,
                    existing_embeddings={},
                    metadata={'user_id': self.conversation_id})
            if msg_id in enable_ids:
                if len(enable_ids) > 1:
                    self.memory_snapshot[idx].enable_idxs.remove(msg_id)
                else:
                    self.memory.delete(self.memory_snapshot[idx].memory_id)
                    self.memory_snapshot.pop(idx)
                    idx -= 1  # After pop, the next item becomes the current idx

            idx += 1

    def add(self, messages: List[Message], msg_id: int) -> None:
        self.cache_messages[msg_id] = messages, self._hash_block(messages)

        messages_dict = []
        for message in messages:
            if isinstance(message, Message):
                messages_dict.append(message.to_dict())
            else:
                messages_dict.append(message)
        self.memory.add(messages_dict, user_id=self.conversation_id)

        self.max_msg_id = max(self.max_msg_id, msg_id)
        res = self.memory.get_all(user_id=self.conversation_id)  # sorted
        res = [(item['id'], item['memory']) for item in res['results']]
        if len(res):
            logger.info('Add memory success. All memory info:')
        for item in res:
            logger.info(item[1])
        valids = []
        unmatched = []
        for id, memory in res:
            matched = False
            for item in self.memory_snapshot:
                if id == item.memory_id:
                    if item.value == memory and item.valid:
                        matched = True
                        valids.append(id)
                        break
                    else:
                        if item.valid:
                            item.disable(msg_id)
            if not matched:
                unmatched.append((id, memory))
        for item in self.memory_snapshot:
            if item.memory_id not in valids:
                item.disable(msg_id)
        for (id, memory) in unmatched:
            m = MemoryMapping(memory_id=id, value=memory, enable_idxs=msg_id)
            self.memory_snapshot.append(m)

    def search(self, query: str) -> str:
        relevant_memories = self.memory.search(
            query, user_id=self.conversation_id, limit=3)
        memories_str = '\n'.join(f"- {entry['memory']}"
                                 for entry in relevant_memories['results'])
        return memories_str

    def _split_into_blocks(self,
                           messages: List[Message]) -> List[List[Message]]:
        """
        Split messages into blocks where each block starts with a 'user' message
        and includes all following non-user messages until the next 'user' (exclusive).

        The very first messages before the first 'user' (e.g., system) are attached to the first user block.
        If no user message exists, all messages go into one block.
        """
        if not messages:
            return []

        blocks: List[List[Message]] = []
        current_block: List[Message] = []

        # Handle leading non-user messages (like system)
        have_user = False
        for msg in messages:
            if msg.role != 'user':
                current_block.append(msg)
            else:
                if have_user:
                    blocks.append(current_block)
                    current_block = [msg]
                else:
                    current_block.append(msg)
                    have_user = True

        # Append the last block
        if current_block:
            blocks.append(current_block)

        return blocks

    def _hash_block(self, block: List[Message]) -> str:
        """Compute sha256 hash of a message block for comparison"""
        data = [message.to_dict() for message in block]
        allow_role = ['user', 'system', 'assistant', 'tool']
        allow_role = [
            role for role in allow_role if role not in self.ignore_role
        ]
        allow_fields = ['reasoning_content', 'content', 'tool_calls', 'role']
        allow_fields = [
            field for field in allow_fields if field not in self.ignore_fields
        ]

        data = [{
            field: value
            for field, value in msg.items() if field in allow_fields
        } for msg in data if msg['role'] in allow_role]

        block_data = json5.dumps(data)
        return hashlib.sha256(block_data.encode('utf-8')).hexdigest()

    def _analyze_messages(
            self,
            messages: List[Message]) -> Tuple[List[List[Message]], List[int]]:
        """
        Analyze incoming messages against cache.

        Returns:
            should_add_messages: blocks to add (not in cache or hash changed)
            should_delete: list of msg_id to delete (in cache but not in new blocks)
        """
        new_blocks = self._split_into_blocks(messages)
        self.cache_messages = dict(sorted(self.cache_messages.items()))

        cache_messages = [(key, value)
                          for key, value in self.cache_messages.items()]
        first_unmatched_idx = -1
        for idx in range(len(new_blocks)):
            block_hash = self._hash_block(new_blocks[idx])
            if idx < len(cache_messages) - 1 and str(block_hash) == str(
                    cache_messages[idx][1][1]):
                continue
            first_unmatched_idx = idx
            break
        should_delete = [
            item[0] for item in cache_messages[first_unmatched_idx:]
        ] if first_unmatched_idx != -1 else []
        should_add_messages = new_blocks[first_unmatched_idx:]

        return should_add_messages, should_delete

    def _get_user_message(self, block: List[Message]) -> Optional[Message]:
        """Helper: get the user message from a block, if exists"""
        for msg in block:
            if msg.role == 'user':
                return msg
        return None

    def _should_update_memory(self, messages: List[Message]) -> bool:
        # TODO: Avoid unnecessary frequent updates and reduce the number of update operations
        return True

    async def run(self, messages, ignore_role=None, ignore_fields=None):
        if not self.is_retrieve or not self._should_update_memory(messages):
            return messages
        should_add_messages, should_delete = self._analyze_messages(messages)

        if should_delete:
            if self.history_mode == 'overwrite':
                for msg_id in should_delete:
                    self.delete_single(msg_id=msg_id)
                res = self.memory.get_all(
                    user_id=self.conversation_id)  # sorted
                res = [(item['id'], item['memory']) for item in res['results']]
                logger.info('Roll back success. All memory info:')
                for item in res:
                    logger.info(item[1])
        if should_add_messages:
            for messages in should_add_messages:
                self.max_msg_id += 1
                self.add(messages, msg_id=self.max_msg_id)
        self.save_cache()

        query = getattr(messages[-1], 'content')
        memories_str = self.search(query)
        # Remove the messages section corresponding to memory, and add the related memory_str information
        if getattr(messages[0], 'role') == 'system':
            system_prompt = getattr(
                messages[0], 'content') + f'\nUser Memories: {memories_str}'
        else:
            system_prompt = f'\nYou are a helpful assistant. Answer the question based on query and memories.\n' \
                            f'User Memories: {memories_str}'
        diff_idx = len(messages) - sum(
            [len(block) for block in should_add_messages])
        new_messages = [Message(role='system', content=system_prompt)
                        ] + messages[diff_idx:]
        return new_messages

    def _init_memory_obj(self):
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
            self.config.memory, 'fact_retrieval_prompt', get_fact_retrieval_prompt())
        memory = mem0.Memory.from_config(mem0_config)
        return memory
