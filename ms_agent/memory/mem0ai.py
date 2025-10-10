# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Message
from ms_agent.utils import get_code_fact_retrieval_prompt, get_logger
from omegaconf import DictConfig

from .base import Memory

logger = get_logger()


class SharedMemoryManager:
    """Manager for shared memory instances across different agents."""
    _instances: Dict[str, 'Mem0Memory'] = {}

    @classmethod
    def get_shared_memory(cls, config: DictConfig) -> 'Mem0Memory':
        """Get or create a shared memory instance based on configuration."""
        # Create a unique key based on memory configuration
        user_id = getattr(config, 'user_id', 'default_user')
        embedding_model = getattr(config, 'embedding_model',
                                  'text-embedding-v4')
        summary_model = getattr(config, 'summary_model', 'gpt-5-2025-08-07')

        key = f'{user_id}_{embedding_model}_{summary_model}'

        if key not in cls._instances:
            logger.info(f'Creating new shared memory instance for key: {key}')
            cls._instances[key] = Mem0Memory(config)
        else:
            logger.info(
                f'Reusing existing shared memory instance for key: {key}')

        return cls._instances[key]

    @classmethod
    def clear_shared_memory(cls, config: DictConfig = None):
        """Clear shared memory instances. If config is provided, clear specific instance."""
        if config is None:
            cls._instances.clear()
            logger.info('Cleared all shared memory instances')
        else:
            user_id = getattr(config, 'user_id', 'default_user')
            embedding_model = getattr(config, 'embedding_model',
                                      'text-embedding-v4')
            summary_model = getattr(config, 'summary_model',
                                    'gpt-5-2025-08-07')
            key = f'{user_id}_{embedding_model}_{summary_model}'

            if key in cls._instances:
                del cls._instances[key]
                logger.info(f'Cleared shared memory instance for key: {key}')
            else:
                logger.warning(
                    f'No shared memory instance found for key: {key}')


class Mem0Memory(Memory):
    """Mem0 memory implementation for AI agents with long-term memory capabilities."""

    def __init__(self, config: DictConfig):
        """Initialize Mem0 memory.

        Args:
            config: Configuration object containing memory settings
        """
        self.config = config
        self.memory = None
        self.global_config = None
        self._lock = asyncio.Lock(
        )  # Add lock for thread safety in shared usage
        self._initialize_memory()

    def patched_parse_messages(self, messages: List[Message]) -> List[Message]:
        response = ''
        for msg in messages:
            if msg['role'] == 'system':
                response += f"system: {msg['content']}\n"
            if msg['role'] == 'user':
                response += f"user: {msg['content']}\n"
            if msg['role'] == 'assistant' and msg['content'] is not None:
                response += f"assistant: {msg['content']}\n"
            if msg['role'] == 'tool':
                response += f"tool: {msg['content']}\n"
        return response

    def set_global_config(self, global_config: DictConfig):
        """Set the global configuration to access LLM settings."""
        self.global_config = global_config
        # Re-initialize if already initialized
        if hasattr(self, 'memory'):
            self._initialize_memory()

    def _initialize_memory(self):
        """Initialize the Mem0 memory instance."""
        try:
            from mem0 import Memory as Mem0MemoryClient
            from mem0.configs.base import MemoryConfig
            import mem0.memory.main
            import mem0.memory.utils

            # Monkey patch Mem0's parse_messages function to handle tool messages
            mem0.memory.main.parse_messages = self.patched_parse_messages
            # Also update the imported reference in utils module
            mem0.memory.utils.FACT_RETRIEVAL_PROMPT = get_code_fact_retrieval_prompt(
            )

            embedding_model = 'text-embedding-3-small'
            summary_model = 'gpt-5-2025-08-07'

            # Check if embedding model and summray model is specified in memory config
            if hasattr(self.config,
                       'embedding_model') and self.config.embedding_model:
                embedding_model = self.config.embedding_model

            if hasattr(self.config,
                       'summary_model') and self.config.summary_model:
                summary_model = self.config.summary_model

            # Configure Mem0 with API key and models
            memory_config = {
                'embedder': {
                    'provider': 'openai',
                    'config': {
                        'model':
                        embedding_model,
                        'openai_base_url':
                        getattr(self.config, 'embedder_base_url',
                                self.config.llm.openai_base_url),
                        'api_key':
                        getattr(self.config, 'embedder_api_key',
                                self.config.llm.openai_api_key),
                    }
                },
                'llm': {
                    'provider': 'openai',
                    'config': {
                        'model':
                        summary_model,
                        'openai_base_url':
                        getattr(self.config, 'llm_base_url',
                                self.config.llm.openai_base_url),
                        'api_key':
                        getattr(self.config, 'llm_api_key',
                                self.config.llm.openai_api_key)
                    }
                },
            }

            config = MemoryConfig(**memory_config)
            self.memory = Mem0MemoryClient(config=config)
            logger.info(
                f'Mem0 memory initialized with embedding model: {embedding_model}, summary model: {summary_model}'
            )
            logger.info('Mem0 memory initialized successfully')

        except ImportError as e:
            logger.error(
                f'Failed to import mem0: {e}. Please install mem0ai package.')
            raise
        except Exception as e:
            logger.error(f'Failed to initialize Mem0 memory: {e}')
            # Don't raise here, just log and continue without memory
            self.memory = None

    async def run(self, messages: List[Message]) -> List[Message]:
        """Process messages and update/add memories.

        Args:
            messages: List of messages to process

        Returns:
            Updated list of messages with memory context
        """
        async with self._lock:  # Protect concurrent access to shared memory
            if not self.memory:
                logger.warning('Mem0 memory not initialized')
                return messages

            try:
                # Get user_id and agent_id from config or use default
                user_id = getattr(self.config, 'user_id',
                                  None) or 'default_user'

                # Get the latest user message for searching memories
                latest_message = self._get_latest_user_message(messages)
                if not latest_message:
                    return messages

                # Search for relevant memories
                conversation_search_limit = getattr(
                    self.config, 'conversation_search_limit', None) or 3
                procedural_search_limit = getattr(
                    self.config, 'procedural_search_limit', None) or 3

                try:
                    conversation_memories = self.memory.search(
                        query=latest_message,
                        user_id=user_id,
                        limit=conversation_search_limit)

                    procedural_memories = self.memory.search(
                        query=latest_message,
                        user_id='subagent',
                        limit=procedural_search_limit)
                    relevant_memories = {'results': []}
                    if conversation_memories and isinstance(
                            conversation_memories,
                            dict) and 'results' in conversation_memories:
                        relevant_memories['results'].extend(
                            conversation_memories['results'])
                    if procedural_memories and isinstance(
                            procedural_memories,
                            dict) and 'results' in procedural_memories:
                        relevant_memories['results'].extend(
                            procedural_memories['results'])

                    logger.info(f'Relevant memories: {relevant_memories}')

                    # Extract memories from results
                    memories = []
                    if relevant_memories and 'results' in relevant_memories:
                        memories = [
                            entry['memory']
                            for entry in relevant_memories['results']
                            if 'memory' in entry
                        ]
                except Exception as search_error:
                    logger.warning(
                        f'Failed to search memories: {search_error}')
                    memories = []

                # If we have relevant memories, add them to the system message
                if memories:
                    messages = self._inject_memories_into_messages(
                        messages, memories)

                return messages

            except Exception as e:
                logger.error(f'Error processing messages with Mem0: {e}')
                return messages

    def _get_latest_user_message(self,
                                 messages: List[Message]) -> Optional[str]:
        """Get the latest user message content."""
        for message in reversed(messages):
            if message.role == 'user' and hasattr(message, 'content'):
                return message.content
        return None

    def _inject_memories_into_messages(self, messages: List[Message],
                                       memories: List[str]) -> List[Message]:
        """Inject relevant memories into the system message."""
        if not memories:
            return messages

        # Format memories for injection
        memory_text = 'User Memories:\n' + '\n'.join(f'- {memory}'
                                                     for memory in memories)

        # Find system message
        system_message = None
        for message in messages:
            if message.role == 'system':
                system_message = message
                break

        if system_message and hasattr(system_message, 'content'):
            # Append memories to existing system message
            system_message.content = system_message.content.split(
                '\n\nUser Memories:\n')[0]
            system_message.content += f'\n\n{memory_text}'
        else:
            # Create new system message with memories
            from ms_agent.llm.utils import Message
            new_system_message = Message(role='system', content=memory_text)
            messages.insert(0, new_system_message)

        return messages

    def add_memories_from_procedural(self, messages: List[Message],
                                     user_id: str, agent_id: str,
                                     memory_type: str):
        """Add new memories from the conversation."""
        if not self.memory:
            return
        try:
            # Convert messages to the format expected by Mem0
            # Properly handle tool_calls and tool messages
            mem0_messages = []
            for message in messages:
                if hasattr(message, 'role') and hasattr(message, 'content'):
                    msg_dict = {
                        'role': message.role,
                        'content': message.content
                    }

                    # Add tool_calls if present (for assistant messages)
                    if hasattr(message, 'tool_calls') and message.tool_calls:
                        # Convert tool_calls to OpenAI format
                        openai_tool_calls = []
                        for tool_call in message.tool_calls:
                            openai_tool_call = {
                                'id':
                                tool_call.get(
                                    'id', f'call_{len(openai_tool_calls)}'),
                                'type':
                                tool_call.get('type', 'function'),
                                'function': {
                                    'name': tool_call.get('tool_name', ''),
                                    'arguments':
                                    tool_call.get('arguments', '{}')
                                }
                            }
                            openai_tool_calls.append(openai_tool_call)
                        msg_dict['tool_calls'] = openai_tool_calls

                    # Add tool_call_id if present (for tool messages)
                    if hasattr(message,
                               'tool_call_id') and message.tool_call_id:
                        msg_dict['tool_call_id'] = message.tool_call_id

                    mem0_messages.append(msg_dict)
            if mem0_messages:  # Only add if we have messages to add
                # Add memories
                self.memory.add(
                    mem0_messages,
                    user_id=user_id,
                    agent_id=agent_id,
                    memory_type=memory_type)
                logger.debug(
                    f'Added memories for agent id {agent_id}, memory type {memory_type}'
                )
        except Exception as e:
            logger.error(f'Error adding memories: {e}')
            # Don't re-raise, just log the error

    def add_memories_from_conversation(self, messages: List[Message],
                                       user_id: str):
        """Add new memories from the conversation."""
        if not self.memory:
            return
        try:
            # Convert messages to the format expected by Mem0
            mem0_messages = []
            for message in messages:
                if hasattr(message, 'role') and hasattr(message, 'content'):
                    mem0_messages.append({
                        'role': message.role,
                        'content': message.content
                    })
            if mem0_messages:  # Only add if we have messages to add
                # Add memories
                self.memory.add(mem0_messages, user_id=user_id)
                logger.debug(f'Added memories for user id {user_id}')
        except Exception as e:
            logger.error(f'Error adding memories: {e}')
            # Don't re-raise, just log the error
