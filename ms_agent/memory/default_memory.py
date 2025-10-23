# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import hashlib
import os
from datetime import datetime
from functools import partial, wraps
from typing import Any, Dict, List, Optional, Tuple

import json
import json5
from ms_agent.llm.utils import Message
from ms_agent.memory import Memory
from ms_agent.utils import get_fact_retrieval_prompt
from ms_agent.utils.constants import get_service_config
from ms_agent.utils.logger import logger
from omegaconf import DictConfig, OmegaConf

DEFAULT_SEARCH_LIMIT = 3


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

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.user_id: Optional[str] = getattr(self.config, 'user_id',
                                              'default_user')
        self.agent_id: Optional[str] = getattr(self.config, 'agent_id', None)
        self.run_id: Optional[str] = getattr(self.config, 'run_id', None)
        self.compress: Optional[bool] = getattr(config, 'compress', True)
        self.is_retrieve: Optional[bool] = getattr(config, 'is_retrieve', True)
        self.path: Optional[str] = getattr(self.config, 'path', 'output')
        self.history_mode = getattr(config, 'history_mode', 'add')
        self.ignore_roles: List[str] = getattr(config, 'ignore_roles',
                                               ['tool', 'system'])
        self.ignore_fields: List[str] = getattr(config, 'ignore_fields',
                                                ['reasoning_content'])
        self.search_limit: int = getattr(config, 'search_limit',
                                         DEFAULT_SEARCH_LIMIT)
        # Add lock for thread safety in shared usage
        self._lock = asyncio.Lock()
        self.memory = self._init_memory_obj()
        self.init_cache_messages()

    def init_cache_messages(self):
        self.load_cache()
        if len(self.cache_messages) and not len(self.memory_snapshot):
            for id, messages in self.cache_messages.items():
                self.add_single(messages, msg_id=id)

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
                metadata = {'user_id': self.user_id}
                if self.agent_id:
                    metadata['agent_id'] = self.agent_id
                if self.run_id:
                    metadata['run_id'] = self.run_id
                self.memory._create_memory(
                    data=self.memory_snapshot[idx].value,
                    existing_embeddings={},
                    metadata=metadata)
            if msg_id in enable_ids:
                if len(enable_ids) > 1:
                    self.memory_snapshot[idx].enable_idxs.remove(msg_id)
                else:
                    self.memory.delete(self.memory_snapshot[idx].memory_id)
                    self.memory_snapshot.pop(idx)
                    idx -= 1  # After pop, the next item becomes the current idx

            idx += 1

    async def add_single(self,
                         messages: List[Message],
                         user_id: Optional[int] = None,
                         agent_id: Optional[int] = None,
                         run_id: Optional[int] = None,
                         memory_type: Optional[str] = None,
                         msg_id: Optional[int] = None) -> None:
        messages_dict = []
        for message in messages:
            if isinstance(message, Message):
                messages_dict.append(message.to_dict_clean())
            else:
                messages_dict.append(message)
        async with self._lock:
            if msg_id is None:
                self.max_msg_id += 1
                msg_id = self.max_msg_id
            else:
                self.max_msg_id = max(msg_id, self.max_msg_id)
            self.cache_messages[msg_id] = messages, self._hash_block(messages)

            try:
                self.memory.add(
                    messages_dict,
                    user_id=user_id or self.user_id,
                    agent_id=agent_id or self.agent_id,
                    run_id=run_id or self.run_id,
                    memory_type=memory_type)
            except Exception as e:
                logger.warning(f'Failed to add memory: {e}')

            if self.history_mode == 'overwrite':
                res = self.memory.get_all(
                    user_id=user_id or self.user_id,
                    agent_id=agent_id or self.agent_id,
                    run_id=run_id or self.run_id)  # sorted
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
                    m = MemoryMapping(
                        memory_id=id, value=memory, enable_idxs=msg_id)
                    self.memory_snapshot.append(m)

    def search(self,
               query: str,
               meta_infos: List[Dict[str, Any]] = None) -> List[str]:
        """
        Search for relevant memories based on a query string and optional metadata filters.

        This method performs one or more searches against the internal memory store using
        provided metadata constraints (e.g., user_id, agent_id, run_id). Each entry in
        `meta_infos` defines a separate search context. If `meta_infos` is not provided,
        a default search is performed using the instance's attributes.

        Args:
            query (str): The input query string used for semantic or keyword-based retrieval.
            meta_infos (List[Dict[str, Any]], optional):
                A list of dictionaries specifying metadata filters for each search request.
                Each dictionary may include:
                    - user_id (str, optional): Filter memories by user ID.
                    - agent_id (str, optional): Filter memories by agent ID.
                    - run_id (str, optional): Filter memories by session/run ID.
                    - limit (int, optional): Maximum number of results to return per search.
                If None, a single default search is performed using instance-level values.

        Returns:
            List[str]: A flattened list of memory content strings from all search results.
                       Each string represents a relevant memory entry.

        Note:
            - For any missing field in a meta_info dict, the instance's corresponding attribute
              (self.user_id, self.agent_id, etc.) is used as fallback.
        """
        if meta_infos is None:
            meta_infos = [{
                'user_id': self.user_id,
                'agent_id': self.agent_id,
                'run_id': self.run_id,
                'limit': self.search_limit,
            }]
        memories = []
        for meta_info in meta_infos:
            user_id = meta_info.get('user_id', None)
            agent_id = meta_info.get('agent_id', None)
            run_id = meta_info.get('run_id', None)
            limit = meta_info.get('limit', self.search_limit)

            relevant_memories = self.memory.search(
                query,
                user_id=user_id or self.user_id,
                agent_id=agent_id or self.agent_id,
                run_id=run_id or self.run_id,
                limit=limit)
            memories.extend(
                [entry['memory'] for entry in relevant_memories['results']])
        return memories

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
        data = [message.to_dict_clean() for message in block]
        allow_role = ['user', 'system', 'assistant', 'tool']
        allow_role = [
            role for role in allow_role if role not in self.ignore_roles
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

    async def add(
        self,
        messages: List[Message],
        user_id: Optional[List[str]] = None,
        agent_id: Optional[List[str]] = None,
        run_id: Optional[List[str]] = None,
        memory_type: Optional[List[str]] = None,
    ) -> None:
        should_add_messages, should_delete = self._analyze_messages(messages)

        if should_delete:
            if self.history_mode == 'overwrite':
                for msg_id in should_delete:
                    self.delete_single(msg_id=msg_id)
                res = self.memory.get_all(
                    user_id=user_id or self.user_id,
                    agent_id=agent_id or self.agent_id,
                    run_id=run_id or self.run_id)  # sorted
                res = [(item['id'], item['memory']) for item in res['results']]
                logger.info('Roll back success. All memory info:')
                for item in res:
                    logger.info(item[1])
        if should_add_messages:
            for messages in should_add_messages:
                await self.add_single(
                    messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    run_id=run_id,
                    memory_type=memory_type)
        self.save_cache()

    def _get_latest_user_message(self,
                                 messages: List[Message]) -> Optional[str]:
        """Get the latest user message content."""
        for message in reversed(messages):
            if message.role == 'user' and hasattr(message, 'content'):
                return message.content
        return None

    def _inject_memories_into_messages(self, messages: List[Message],
                                       memories: List[str],
                                       keep_details) -> List[Message]:
        """Inject relevant memories into the system message."""
        # Format memories for injection
        memories_str = 'User Memories:\n' + '\n'.join(f'- {memory}'
                                                      for memory in memories)
        # Remove the messages section corresponding to memory, and add the related memory_str information

        if getattr(messages[0], 'role') == 'system':
            system_prompt = getattr(
                messages[0], 'content') + f'\nUser Memories: {memories_str}'
            remain_idx = 1
        else:
            system_prompt = f'\nYou are a helpful assistant. Answer the question based on query and memories.\n' \
                            f'User Memories: {memories_str}'
            remain_idx = 0
        if not keep_details:
            should_add_messages, should_delete = self._analyze_messages(
                messages)
            remain_idx = max(
                remain_idx,
                len(messages)
                - sum([len(block) for block in should_add_messages]))

        new_messages = [Message(role='system', content=system_prompt)
                        ] + messages[remain_idx:]
        return new_messages

    async def run(
        self,
        messages: List[Message],
        meta_infos: List[Dict[str, Any]] = None,
        keep_details: bool = True,
    ):
        if not self.is_retrieve:
            return messages

        query = self._get_latest_user_message(messages)
        if not query:
            return messages
        async with self._lock:
            try:
                memories = self.search(query, meta_infos)
            except Exception as search_error:
                logger.warning(f'Failed to search memories: {search_error}')
                memories = []
            if memories:
                messages = self._inject_memories_into_messages(
                    messages, memories, keep_details)
            return messages

    def _init_memory_obj(self):
        try:
            import mem0
        except ImportError as e:
            logger.error(
                f'Failed to import mem0: {e}. Please install mem0ai package via `pip install mem0ai`.'
            )
            raise

        parse_messages_origin = mem0.memory.main.parse_messages
        capture_event_origin = mem0.memory.main.capture_event

        @wraps(parse_messages_origin)
        def patched_parse_messages(messages, ignore_roles):
            response = ''
            for msg in messages:
                if 'system' not in ignore_roles and msg['role'] == 'system':
                    response += f"system: {msg['content']}\n"
                if msg['role'] == 'user':
                    response += f"user: {msg['content']}\n"
                if msg['role'] == 'assistant' and msg['content'] is not None:
                    response += f"assistant: {msg['content']}\n"
                if 'tool' not in ignore_roles and msg['role'] == 'tool':
                    response += f"tool: {msg['content']}\n"
            return response

        @wraps(capture_event_origin)
        def patched_capture_event(event_name,
                                  memory_instance,
                                  additional_data=None):
            pass

        mem0.memory.main.parse_messages = partial(
            patched_parse_messages,
            ignore_roles=self.ignore_roles,
        )

        mem0.memory.main.capture_event = partial(patched_capture_event, )

        if not self.is_retrieve:
            return

        embedding_dims = None
        if getattr(self.config, 'embedder', None) is not None:
            service = getattr(self.config.embedder, 'service', 'dashscope')
            emb_model = getattr(self.config.embedder, 'model',
                                'text-embedding-v4')
            embedding_dims = getattr(self.config.embedder, 'embedding_dims',
                                     None)
        else:
            service = 'dashscope'
            emb_model = 'text-embedding-v4'

        embedder = OmegaConf.create({
            'provider': 'openai',
            'config': {
                'api_key': os.getenv(f'{service.upper()}_API_KEY'),
                'openai_base_url': get_service_config(service).base_url,
                'model': emb_model,
                'embedding_dims': embedding_dims
            }
        })

        llm = {}
        if self.compress:
            service = getattr(self.config.llm, 'service', 'dashscope')
            llm_model = getattr(self.config.llm, 'model', None)
            api_key = getattr(self.config.llm, 'openai_api_key', None)
            openai_base_url = getattr(self.config.llm, 'openai_base_url', None)
            max_tokens = getattr(self.config.llm, 'max_tokens', None)

            llm = {
                'provider': 'openai',
                'config': {
                    'model':
                    llm_model,
                    'api_key':
                    api_key or os.getenv(f'{service.upper()}_API_KEY'),
                    'openai_base_url':
                    openai_base_url or get_service_config(service).base_url,
                }
            }
            if max_tokens is not None:
                llm['config']['max_tokens'] = max_tokens

        vector_store_service = getattr(
            self.config.vector_store, 'service', 'qdrant') if hasattr(
                self.config, 'vector_store') else 'qdrant'
        on_disk = getattr(
            self.config.vector_store, 'on_disk', True) if hasattr(
                self.config, 'vector_store') else True
        path = getattr(self.config.vector_store, 'path', self.path) if hasattr(
            self.config, 'vector_store') else self.path
        db_name = getattr(
            self.config.vector_store, 'db_name', None) if hasattr(
                self.config, 'vector_store') else None
        vector_store = {
            'provider': vector_store_service,
            'config': {
                'path': path,
                'on_disk': on_disk,
                'collection_name': path,
            }
        }
        if isinstance(embedding_dims, int):
            vector_store['config']['embedding_model_dims'] = embedding_dims
        if db_name is not None:
            vector_store['config']['db_name'] = db_name

        mem0_config = {
            'is_infer': self.compress,
            'llm': llm,
            'vector_store': vector_store,
            'embedder': embedder
        }
        logger.info(f'Memory config: {mem0_config}')
        # Prompt content is too long, default logging reduces readability
        mem0_config['custom_fact_extraction_prompt'] = getattr(
            self.config, 'fact_retrieval_prompt', get_fact_retrieval_prompt()
        ) + f'Today\'s date is {datetime.now().strftime("%Y-%m-%d")}.'
        try:
            memory = mem0.Memory.from_config(mem0_config)
            memory._telemetry_vector_store = None
        except Exception as e:
            logger.error(f'Failed to initialize Mem0 memory: {e}')
            # Don't raise here, just log and continue without memory
            memory = None
        return memory
