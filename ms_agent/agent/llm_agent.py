# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import importlib
import inspect
import os.path
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback, callbacks_mapping
from ms_agent.llm.llm import LLM
from ms_agent.llm.utils import Message, ToolResult
from ms_agent.memory import Memory, get_memory_meta_safe, memory_mapping
from ms_agent.memory.memory_manager import SharedMemoryManager
from ms_agent.rag.base import RAG
from ms_agent.rag.utils import rag_mapping
from ms_agent.tools import ToolManager
from ms_agent.utils import async_retry, read_history, save_history
from ms_agent.utils.constants import DEFAULT_TAG, DEFAULT_USER
from ms_agent.utils.logger import logger
from omegaconf import DictConfig, OmegaConf

from ..config.config import Config, ConfigLifecycleHandler
from .base import Agent


class LLMAgent(Agent):
    """
    An agent designed to run LLM-based tasks with support for tools, memory, planning, and callbacks.

    This class provides a full lifecycle for running an LLM agent, including:
    - Prompt preparation
    - Chat history management
    - External tool calling
    - Memory retrieval and updating
    - Planning logic
    - Stream or non-stream response generation
    - Callback hooks at various stages of execution

    Args:
        config (DictConfig): Pre-loaded configuration object.
        tag (str): The name of this class defined by the user.
        trust_remote_code (bool): Whether to trust remote code if any.
        **kwargs: Additional keyword arguments passed to the parent Agent constructor.
    """

    AGENT_NAME = 'LLMAgent'

    DEFAULT_SYSTEM = 'You are a helpful assistant.'

    DEFAULT_MAX_CHAT_ROUND = 20

    TOTAL_PROMPT_TOKENS = 0
    TOTAL_COMPLETION_TOKENS = 0
    TOKEN_LOCK = asyncio.Lock()

    def __init__(self,
                 config: DictConfig = DictConfig({}),
                 tag: str = DEFAULT_TAG,
                 trust_remote_code: bool = False,
                 **kwargs):
        if not hasattr(config, 'llm'):
            default_yaml = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), 'agent.yaml')
            llm_config = Config.from_task(default_yaml)
            config = OmegaConf.merge(llm_config, config)
        super().__init__(config, tag, trust_remote_code)
        self.callbacks: List[Callback] = []
        self.tool_manager: Optional[ToolManager] = None
        self.memory_tools: List[Memory] = []
        self.rag: Optional[RAG] = None
        self.llm: Optional[LLM] = None
        self.runtime: Optional[Runtime] = None
        self.max_chat_round: int = 0
        self.load_cache = kwargs.get('load_cache', False)
        self.config.load_cache = self.load_cache
        self.mcp_server_file = kwargs.get('mcp_server_file', None)
        self.mcp_config: Dict[str, Any] = self.parse_mcp_servers(
            kwargs.get('mcp_config', {}))
        self.mcp_client = kwargs.get('mcp_client', None)
        self.config_handler = self.register_config_handler()

    def register_callback(self, callback: Callback):
        """
        Register a new callback to be triggered during the agent's lifecycle.

        Args:
            callback (Callback): The callback instance to add.
        """
        self.callbacks.append(callback)

    def parse_mcp_servers(self, mcp_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse MCP server configurations from a file or dictionary.

        Args:
            mcp_config (Dict[str, Any]): Raw MCP configuration data.

        Returns:
            Dict[str, Any]: Merged configuration including file-based overrides.
        """
        mcp_config = mcp_config or {}
        if self.mcp_server_file is not None and os.path.isfile(
                self.mcp_server_file):
            with open(self.mcp_server_file, 'r') as f:
                config = json.load(f)
                config.update(mcp_config)
                return config
        return mcp_config

    @contextmanager
    def config_context(self):
        if self.config_handler is not None:
            self.config = self.config_handler.task_begin(self.config, self.tag)
        yield
        if self.config_handler is not None:
            self.config = self.config_handler.task_end(self.config, self.tag)

    def register_config_handler(self) -> Optional[ConfigLifecycleHandler]:
        """
        Registers a `ConfigLifecycleHandler` based on the configuration's `handler` field.

        This method dynamically imports and instantiates a subclass of `ConfigLifecycleHandler`
        defined in an external module. Requires `trust_remote_code=True` and a valid `local_dir`.

        Raises:
            AssertionError: If the handler cannot be found or loaded due to security restrictions or invalid paths.
        """
        handler_file = getattr(self.config, 'handler', None)
        if handler_file is not None:
            local_dir = self.config.local_dir
            assert self.config.trust_remote_code, (
                f'[External Code]A Config Lifecycle handler '
                f'registered in the config: {handler_file}. '
                f'\nThis is external code, if you trust this workflow, '
                f'please specify `--trust_remote_code true`')
            assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
            if local_dir not in sys.path:
                sys.path.insert(0, local_dir)

            handler_module = importlib.import_module(handler_file)
            module_classes = {
                name: cls
                for name, cls in inspect.getmembers(handler_module,
                                                    inspect.isclass)
            }
            handler = None
            for name, handler_cls in module_classes.items():
                if handler_cls.__bases__[
                        0] is ConfigLifecycleHandler and handler_cls.__module__ == handler_file:
                    handler = handler_cls()
            assert handler is not None, f'Config Lifecycle handler class cannot be found in {handler_file}'
            return handler
        return None

    def register_callback_from_config(self):
        """
        Dynamically load and instantiate callbacks defined in the configuration.

        Raises:
            AssertionError: If untrusted external code is referenced without permission.
        """
        local_dir = self.config.local_dir if hasattr(self.config,
                                                     'local_dir') else None
        if hasattr(self.config, 'callbacks'):
            callbacks = self.config.callbacks or []
            for _callback in callbacks:
                subdir = os.path.dirname(_callback)
                assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
                if subdir:
                    subdir = os.path.join(local_dir, str(subdir))
                _callback = os.path.basename(_callback)
                if _callback not in callbacks_mapping:
                    if not self.trust_remote_code:
                        raise AssertionError(
                            '[External Code Found] Your config file contains external code, '
                            'instantiate the code may be UNSAFE, if you trust the code, '
                            'please pass `trust_remote_code=True` or `--trust_remote_code true`'
                        )
                    if local_dir not in sys.path:
                        sys.path.insert(0, local_dir)
                    if subdir and subdir not in sys.path:
                        sys.path.insert(0, subdir)
                    if _callback.endswith('.py'):
                        _callback = _callback[:-3]
                    callback_file = importlib.import_module(_callback)
                    module_classes = {
                        name: cls
                        for name, cls in inspect.getmembers(
                            callback_file, inspect.isclass)
                    }
                    for name, cls in module_classes.items():
                        # Find cls which base class is `Callback`
                        if issubclass(
                                cls, Callback) and cls.__module__ == _callback:
                            self.callbacks.append(cls(self.config))  # noqa
                else:
                    self.callbacks.append(callbacks_mapping[_callback](
                        self.config))

    async def on_task_begin(self, messages: List[Message]):
        self.log_output(f'Agent {self.tag} task beginning.')
        await self.loop_callback('on_task_begin', messages)

    async def on_task_end(self, messages: List[Message]):
        self.log_output(f'Agent {self.tag} task finished.')
        await self.loop_callback('on_task_end', messages)

    async def on_generate_response(self, messages: List[Message]):
        await self.loop_callback('on_generate_response', messages)

    async def on_tool_call(self, messages: List[Message]):
        await self.loop_callback('on_tool_call', messages)

    async def after_tool_call(self, messages: List[Message]):
        if messages[-1].role == 'assistant' and not messages[-1].tool_calls:
            self.runtime.should_stop = True
        await self.loop_callback('after_tool_call', messages)

    async def loop_callback(self, point, messages: List[Message]):
        """
        Trigger a specific callback hook across all registered callbacks.

        Args:
            point (str): Name of the callback method to call.
            messages (List[Message]): Current message history.
        """
        for callback in self.callbacks:
            await getattr(callback, point)(self.runtime, messages)

    async def parallel_tool_call(self,
                                 messages: List[Message]) -> List[Message]:
        """
        Execute multiple tool calls in parallel and append results to the message list.

        Args:
            messages (List[Message]): Current conversation history.

        Returns:
            List[Message]: Updated message list including tool responses.
        """
        tool_call_result = await self.tool_manager.parallel_call_tool(
            messages[-1].tool_calls)
        assert len(tool_call_result) == len(messages[-1].tool_calls)
        for tool_call_result, tool_call_query in zip(tool_call_result,
                                                     messages[-1].tool_calls):
            tool_call_result_format = ToolResult.from_raw(tool_call_result)
            _new_message = Message(
                role='tool',
                content=tool_call_result_format.text,
                tool_call_id=tool_call_query['id'],
                name=tool_call_query['tool_name'],
                resources=tool_call_result_format.resources)

            if _new_message.tool_call_id is None:
                # If tool call id is None, add a random one
                _new_message.tool_call_id = str(uuid.uuid4())[:8]
                tool_call_query['id'] = _new_message.tool_call_id
            messages.append(_new_message)
            self.log_output(_new_message.content)
        return messages

    async def prepare_tools(self):
        """Initialize and connect the tool manager."""
        self.tool_manager = ToolManager(
            self.config,
            self.mcp_config,
            self.mcp_client,
            trust_remote_code=self.trust_remote_code)
        await self.tool_manager.connect()

    async def cleanup_tools(self):
        """Cleanup resources used by the tool manager."""
        await self.tool_manager.cleanup()

    @property
    def stream(self):
        generation_config = getattr(self.config, 'generation_config',
                                    DictConfig({}))
        return getattr(generation_config, 'stream', False)

    @property
    def system(self):
        return getattr(
            getattr(self.config, 'prompt', DictConfig({})), 'system', None)

    @property
    def query(self):
        query = getattr(
            getattr(self.config, 'prompt', DictConfig({})), 'query', None)
        if not query:
            query = input('>>>')
        return query

    async def create_messages(
            self, messages: Union[List[Message], str]) -> List[Message]:
        """
        Convert input into a standardized list of messages.

        Args:
            messages (Union[List[Message], str]): Input prompt or existing message history.

        Returns:
            List[Message]: Standardized message history including system and user prompts.
        """
        if isinstance(messages, list):
            system = self.system
            if system is not None and messages[
                    0].role == 'system' and system != messages[0].content:
                # Replace the existing system
                messages[0].content = system
        else:
            assert isinstance(
                messages, str
            ), f'inputs can be either a list or a string, but current is {type(messages)}'
            messages = [
                Message(
                    role='system',
                    content=self.system or LLMAgent.DEFAULT_SYSTEM),
                Message(role='user', content=messages or self.query),
            ]
        return messages

    async def do_rag(self, messages: List[Message]):
        if self.rag is not None:
            messages[1].content = await self.rag.query(messages[1].content)

    async def load_memory(self):
        """Initialize and append memory tool instances based on the configuration provided in the global config.

        Raises:
            AssertionError: If a specified memory type in the config does not exist in memory_mapping.
        """
        self.config: DictConfig
        if hasattr(self.config, 'memory'):
            for mem_instance_type, _memory in self.config.memory.items():
                assert mem_instance_type in memory_mapping, (
                    f'{mem_instance_type} not in memory_mapping, '
                    f'which supports: {list(memory_mapping.keys())}')

                shared_memory = await SharedMemoryManager.get_shared_memory(
                    self.config, mem_instance_type)
                self.memory_tools.append(shared_memory)

    async def prepare_rag(self):
        """Load and initialize the RAG component from the config."""
        if hasattr(self.config, 'rag'):
            rag = self.config.rag
            if rag is not None:
                assert rag.name in rag_mapping, (
                    f'{rag.name} not in rag_mapping, '
                    f'which supports: {list(rag_mapping.keys())}')
                self.rag: RAG = rag_mapping(rag.name)(self.config)

    async def condense_memory(self, messages: List[Message]) -> List[Message]:
        """
        Update memory using the current conversation history.

        Args:
            messages (List[Message]): Current message history.

        Returns:
            List[Message]: Possibly updated message history after memory refinement.
        """
        for memory_tool in self.memory_tools:
            messages = await memory_tool.run(messages)
        return messages

    def log_output(self, content: str):
        """
        Log formatted output with a tag prefix.

        Args:
            content (str): Content to log.
        """
        if len(content) > 1024:
            content = content[:512] + '\n...\n' + content[-512:]
        for line in content.split('\n'):
            for _line in line.split('\\n'):
                logger.info(f'[{self.tag}] {_line}')

    def handle_new_response(self, messages: List[Message],
                            response_message: Message):
        assert response_message is not None, 'No response message generated from LLM.'
        if response_message.tool_calls:
            self.log_output('[tool_calling]:')
            for tool_call in response_message.tool_calls:
                tool_call = deepcopy(tool_call)
                if isinstance(tool_call['arguments'], str):
                    try:
                        tool_call['arguments'] = json.loads(
                            tool_call['arguments'])
                    except json.decoder.JSONDecodeError:
                        pass
                self.log_output(
                    json.dumps(tool_call, ensure_ascii=False, indent=4))

        if messages[-1] is not response_message:
            messages.append(response_message)

        if messages[-1].role == 'assistant' and not messages[
                -1].content and response_message.tool_calls:
            messages[-1].content = 'Let me do a tool calling.'

    @async_retry(max_attempts=Agent.retry_count, delay=1.0)
    async def step(
        self, messages: List[Message]
    ) -> AsyncGenerator[List[Message], Any]:  # type: ignore
        """
        Execute a single step in the agent's interaction loop.

        This method performs the following operations in sequence:
        1. Deep copies the current message history to avoid mutation issues.
        2. Refines memory based on the current conversation state.
        3. Triggers pre-response callbacks.
        5. Generates a response from the LLM using available tools.
        6. Optionally streams the response output to stdout.
        7. Triggers post-response callbacks.
        8. Handles parallel tool calls if needed.
        9. Triggers post-tool-call callbacks.
        10. Returns the updated message history.

        The step may be retried up to two times on failure due to the `@async_retry` decorator.

        Args:
            messages (List[Message]): Current message history.

        Returns:
            List[Message]: Updated message history after this step.
        """
        messages = deepcopy(messages)
        if (not self.load_cache) or messages[-1].role != 'assistant':
            messages = await self.condense_memory(messages)
            await self.on_generate_response(messages)
            tools = await self.tool_manager.get_tools()

            if self.stream:
                self.log_output('[assistant]:')
                _content = ''
                is_first = True
                _response_message = None
                for _response_message in self.llm.generate(
                        messages, tools=tools):
                    if is_first:
                        messages.append(_response_message)
                        is_first = False
                    new_content = _response_message.content[len(_content):]
                    sys.stdout.write(new_content)
                    sys.stdout.flush()
                    _content = _response_message.content
                    messages[-1] = _response_message
                    yield messages
                sys.stdout.write('\n')
            else:
                _response_message = self.llm.generate(messages, tools=tools)
                if _response_message.content:
                    self.log_output('[assistant]:')
                    self.log_output(_response_message.content)

            # Response generated
            self.handle_new_response(messages, _response_message)
            await self.on_tool_call(messages)
        else:
            # Set load_cache to `false` to avoid affect later operations
            self.load_cache = False
            # Meaning the latest message is `assistant`, this prevents a different response if there are sub-tasks.
            _response_message = messages[-1]
        self.save_history(messages)

        if _response_message.tool_calls:
            messages = await self.parallel_tool_call(messages)

        await self.after_tool_call(messages)

        # usage
        prompt_tokens = _response_message.prompt_tokens
        completion_tokens = _response_message.completion_tokens

        async with LLMAgent.TOKEN_LOCK:
            LLMAgent.TOTAL_PROMPT_TOKENS += prompt_tokens
            LLMAgent.TOTAL_COMPLETION_TOKENS += completion_tokens

        # tokens in the current step
        self.log_output(
            f'[usage] prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}'
        )
        # total tokens for the process so far
        self.log_output(
            f'[usage_total] total_prompt_tokens: {LLMAgent.TOTAL_PROMPT_TOKENS}, '
            f'total_completion_tokens: {LLMAgent.TOTAL_COMPLETION_TOKENS}')

        yield messages

    def prepare_llm(self):
        """Initialize the LLM model from the configuration."""
        self.llm: LLM = LLM.from_config(self.config)

    def prepare_runtime(self):
        """Initialize the runtime context."""
        self.runtime: Runtime = Runtime(llm=self.llm)

    def read_history(self, messages: List[Message],
                     **kwargs) -> Tuple[DictConfig, Runtime, List[Message]]:
        """
        Load previous chat history from disk if available.

        Args:
            messages (List[Message]): Input message or history to resume from.

        Returns:
            Tuple[DictConfig, Runtime, List[Message]]: Updated config, runtime, and message history.
        """
        if isinstance(messages, str):
            query = messages
        else:
            query = messages[1].content
        if not query or not self.load_cache:
            return self.config, self.runtime, messages

        config, _messages = read_history(self.output_dir, self.tag)
        if config is not None and _messages is not None:
            if hasattr(config, 'runtime'):
                runtime = Runtime(llm=self.llm)
                runtime.from_dict(config.runtime)
                delattr(config, 'runtime')
            else:
                runtime = self.runtime
            if _messages[-1].role == 'tool':
                # Ignore and redo the last tool response
                # This is because it's the last calling, the unhandled error may be started from here
                _messages = _messages[:-1]
            return config, runtime, _messages
        else:
            return self.config, self.runtime, messages

    def get_user_id(self, default_user_id=DEFAULT_USER) -> Optional[str]:
        user_id = default_user_id
        if hasattr(self.config, 'memory') and self.config.memory:
            for memory_config in self.config.memory:
                if hasattr(memory_config, 'user_id') and memory_config.user_id:
                    user_id = memory_config.user_id
                    break
        return user_id

    def _get_step_memory_info(self, memory_config: DictConfig):
        user_id, agent_id, run_id, memory_type = get_memory_meta_safe(
            memory_config, 'add_after_step')
        if all(value is None
               for value in [user_id, agent_id, run_id, memory_type]):
            return None, None, None, None
        user_id = user_id or getattr(memory_config, 'user_id', None)
        return user_id, agent_id, run_id, memory_type

    def _get_run_memory_info(self, memory_config: DictConfig):
        user_id, agent_id, run_id, memory_type = get_memory_meta_safe(
            memory_config,
            'add_after_task',
            default_user_id=getattr(memory_config, 'user_id', None))
        if all(value is None
               for value in [user_id, agent_id, run_id, memory_type]):
            return None, None, None, None
        user_id = user_id or getattr(memory_config, 'user_id', None)
        agent_id = agent_id or self.tag
        memory_type = memory_type or None
        return user_id, agent_id, run_id, memory_type

    async def add_memory(self, messages: List[Message], add_type, **kwargs):
        if hasattr(self.config, 'memory') and self.config.memory:
            tools_num = len(self.memory_tools) if self.memory_tools else 0

            for idx, (mem_instance_type,
                      memory_config) in enumerate(self.config.memory.items()):
                if add_type == 'add_after_task':
                    user_id, agent_id, run_id, memory_type = self._get_run_memory_info(
                        memory_config)
                else:
                    user_id, agent_id, run_id, memory_type = self._get_step_memory_info(
                        memory_config)

                if idx < tools_num:
                    if any(v is not None
                           for v in [user_id, agent_id, run_id, memory_type]):
                        await self.memory_tools[idx].add(
                            messages,
                            user_id=user_id,
                            agent_id=agent_id,
                            run_id=run_id,
                            memory_type=memory_type)

    def save_history(self, messages: List[Message], **kwargs):
        """
        Save current chat history to disk for future resuming.

        Args:
            messages (List[Message]): Current message history to save.
        """
        query = None
        if len(messages) > 1 and messages[1].role == 'user':
            query = messages[1].content
        elif messages:
            query = messages[0].content
        if not query:
            return

        if not getattr(self.config, 'save_history', True):
            return

        config: DictConfig = deepcopy(self.config)
        config.runtime = self.runtime.to_dict()
        save_history(
            self.output_dir, task=self.tag, config=config, messages=messages)

    async def run_loop(self, messages: Union[List[Message], str],
                       **kwargs) -> AsyncGenerator[Any, Any]:
        """Run the agent, mainly contains a llm calling and tool calling loop.

        Args:
            messages (Union[List[Message], str]): Input data for the agent. Can be a raw string prompt,
                                               or a list of previous interaction messages.
        Returns:
            List[Message]: A list of message objects representing the agent's response or interaction history.
        """
        try:
            self.max_chat_round = getattr(self.config, 'max_chat_round',
                                          LLMAgent.DEFAULT_MAX_CHAT_ROUND)
            self.register_callback_from_config()
            self.prepare_llm()
            self.prepare_runtime()
            await self.prepare_tools()
            await self.load_memory()
            await self.prepare_rag()
            self.runtime.tag = self.tag

            if messages is None:
                messages = self.query

            self.config, self.runtime, messages = self.read_history(messages)

            if self.runtime.round == 0:
                # 0 means no history
                messages = await self.create_messages(messages)
                await self.do_rag(messages)
                await self.on_task_begin(messages)

            for message in messages:
                if message.role != 'system':
                    self.log_output('[' + message.role + ']:')
                    self.log_output(message.content)
            while not self.runtime.should_stop:
                async for messages in self.step(messages):
                    yield messages
                self.runtime.round += 1
                # save memory and history
                await self.add_memory(
                    messages, add_type='add_after_step', **kwargs)
                self.save_history(messages)

                # +1 means the next round the assistant may give a conclusion
                if self.runtime.round >= self.max_chat_round + 1:
                    if not self.runtime.should_stop:
                        messages.append(
                            Message(
                                role='assistant',
                                content=
                                f'Task {messages[1].content} was cutted off, because '
                                f'max round({self.max_chat_round}) exceeded.'))
                    self.runtime.should_stop = True
                    yield messages

            # save memory
            await self.on_task_end(messages)
            await self.cleanup_tools()
            yield messages

            def _add_memory():
                asyncio.run(
                    self.add_memory(
                        messages, add_type='add_after_task', **kwargs))

            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _add_memory)
        except Exception as e:
            import traceback
            logger.warning(traceback.format_exc())
            if hasattr(self.config, 'help'):
                logger.error(
                    f'[{self.tag}] Runtime error, please follow the instructions:\n\n {self.config.help}'
                )
            raise e

    async def run(
            self, messages: Union[List[Message], str], **kwargs
    ) -> Union[List[Message], AsyncGenerator[List[Message], Any]]:
        stream = kwargs.get('stream', False)
        with self.config_context():
            if stream:
                OmegaConf.update(
                    self.config, 'generation_config.stream', True, merge=True)

                async def stream_generator():
                    async for _chunk in self.run_loop(
                            messages=messages, **kwargs):
                        yield _chunk

                return stream_generator()
            else:
                res = None
                async for chunk in self.run_loop(messages=messages, **kwargs):
                    res = chunk
                return res
