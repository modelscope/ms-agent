# Copyright (c) Alibaba, Inc. and its affiliates.
import importlib
import inspect
import os.path
import sys
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union

import json
from ms_agent.callbacks import Callback, callbacks_mapping
from ms_agent.llm.llm import LLM
from ms_agent.llm.utils import Message, Tool
from ms_agent.rag.base import Rag
from ms_agent.rag.utils import rag_mapping
from ms_agent.tools import ToolManager
from ms_agent.utils import async_retry
from ms_agent.utils.logger import logger
from omegaconf import DictConfig, OmegaConf

from ..utils.utils import read_history, save_history
from .base import Agent
from .memory import Memory, memory_mapping
from .plan.base import Planer
from .plan.utils import planer_mapping
from .runtime import Runtime


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
        config_dir_or_id (Optional[str]): Path or identifier to load the configuration from.
        config (Optional[DictConfig]): Pre-loaded configuration object.
        env (Optional[Dict[str, str]]): Additional environment variables to inject into the config.
        **kwargs: Additional keyword arguments passed to the parent Agent constructor.
    """

    DEFAULT_SYSTEM = 'You are a helpful assistant.'

    def __init__(self,
                 config_dir_or_id: Optional[str] = None,
                 config: Optional[DictConfig] = None,
                 env: Optional[Dict[str, str]] = None,
                 **kwargs):
        super().__init__(
            config_dir_or_id,
            config,
            env,
            tag=kwargs.get('tag', None),
            trust_remote_code=kwargs.get('trust_remote_code', False))
        self.callbacks: List[Callback] = []
        self.tool_manager: Optional[ToolManager] = None
        self.memory_tools: List[Memory] = []
        self.planer: Optional[Planer] = None
        self.rag: Optional[Rag] = None
        self.llm: Optional[LLM] = None
        self.runtime: Optional[Runtime] = None
        self.max_chat_round: int = 0
        self.task = kwargs.get('task', 'default')
        self.load_cache = kwargs.get('load_cache', False)
        self.mcp_server_file = kwargs.get('mcp_server_file', None)
        self.mcp_config: Dict[str, Any] = self._parse_mcp_servers(
            kwargs.get('mcp_config', {}))
        self._task_begin()

    def register_callback(self, callback: Callback):
        """
        Register a new callback to be triggered during the agent's lifecycle.

        Args:
            callback (Callback): The callback instance to add.
        """
        self.callbacks.append(callback)

    def _parse_mcp_servers(self, mcp_config) -> Dict[str, Any]:
        """
        Parse MCP server configurations from a file or dictionary.

        Args:
            mcp_config (Dict[str, Any]): Raw MCP configuration data.

        Returns:
            Dict[str, Any]: Merged configuration including file-based overrides.
        """
        if self.mcp_server_file is not None and os.path.isfile(
                self.mcp_server_file):
            with open(self.mcp_server_file, 'r') as f:
                config = json.load(f)
                config.update(mcp_config)
                return config
        return mcp_config

    def _register_callback_from_config(self):
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
                            self.callbacks.append(cls(self.config))
                else:
                    self.callbacks.append(callbacks_mapping[_callback](
                        self.config))

    async def _loop_callback(self, point, messages: List[Message]):
        """
        Trigger a specific callback hook across all registered callbacks.

        Args:
            point (str): Name of the callback method to call.
            messages (List[Message]): Current message history.
        """
        for callback in self.callbacks:
            await getattr(callback, point)(self.runtime, messages)

    async def _parallel_tool_call(self,
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
            _new_message = Message(
                role='tool',
                content=tool_call_result,
                tool_call_id=tool_call_query['id'],
                name=tool_call_query['tool_name'])
            messages.append(_new_message)
            self._log_output(_new_message.content, self.tag)
        return messages

    async def _prepare_tools(self):
        """Initialize and connect the tool manager."""
        self.tool_manager = ToolManager(self.config, self.mcp_config)
        await self.tool_manager.connect()

    async def _cleanup_tools(self):
        """Cleanup resources used by the tool manager."""
        await self.tool_manager.cleanup()

    async def _prepare_messages(
            self, inputs: Union[List[Message], str]) -> List[Message]:
        """
        Convert input into a standardized list of messages.

        Args:
            inputs (Union[List[Message], str]): Input prompt or existing message history.

        Returns:
            List[Message]: Standardized message history including system and user prompts.
        """
        if isinstance(inputs, list):
            system = getattr(
                getattr(self.config, 'prompt', DictConfig({})), 'system', None)
            if system is not None and inputs[
                    0].role == 'system' and system != inputs[0].content:
                inputs[0].content = system
            return inputs
        assert isinstance(
            inputs, str
        ), f'inputs can be either a list or a string, but current is {type(inputs)}'
        system = None
        query = None
        if hasattr(self.config, 'prompt'):
            system = getattr(self.config.prompt, 'system', None)
            query = getattr(self.config.prompt, 'query', None)
        messages = [
            Message(role='system', content=system or self.DEFAULT_SYSTEM),
            Message(role='user', content=inputs or query),
        ]
        if self.rag is not None:
            messages = await self.rag.run(messages)
        return messages

    async def _prepare_memory(self):
        """Load and initialize memory components from the config."""
        if hasattr(self.config, 'memory'):
            for _memory in (self.config.memory or []):
                assert _memory.name in memory_mapping, (
                    f'{_memory.name} not in memory_mapping, '
                    f'which supports: {list(memory_mapping.keys())}')
                self.memory_tools.append(memory_mapping[_memory.name](
                    self.config))

    async def _prepare_planer(self):
        """Load and initialize the planer component from the config."""
        if hasattr(self.config, 'planer'):
            planer = self.config.planer
            if planer is not None:
                assert planer.name in planer_mapping, (
                    f'{planer.name} not in planer_mapping, '
                    f'which supports: {list(planer_mapping.keys())}')
                self.planer = planer_mapping[planer.name](self.config)

    async def _prepare_rag(self):
        """Load and initialize the RAG component from the config."""
        if hasattr(self.config, 'rag'):
            rag = self.config.rag
            if rag is not None:
                assert rag.name in rag_mapping, (
                    f'{rag.name} not in rag_mapping, '
                    f'which supports: {list(rag_mapping.keys())}')
                self.rag: Rag = rag_mapping(rag.name)(self.config)

    async def _refine_memory(self, messages: List[Message]) -> List[Message]:
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

    async def _update_plan(self, messages: List[Message]) -> List[Message]:
        """
        Update the current plan based on conversation state.

        Args:
            messages (List[Message]): Current message history.

        Returns:
            List[Message]: Updated message history after plan update.
        """
        if self.planer is not None:
            messages = await self.planer.update_plan(self.runtime, messages)
        return messages

    def _handle_stream_message(self, messages: List[Message],
                               tools: List[Tool]):
        """
        Generator that yields streamed responses from the LLM.

        Args:
            messages (List[Message]): Current message history.
            tools (List[Tool]): Available tools for function calling.

        Yields:
            Message: Streamed output message chunks.
        """
        for message in self.llm.generate(messages, tools=tools):
            yield message

    @staticmethod
    def _log_output(content: str, tag: str):
        """
        Log formatted output with a tag prefix.

        Args:
            content (str): Content to log.
            tag (str): Prefix tag for the log entry.
        """
        for line in content.split('\n'):
            for _line in line.split('\\n'):
                logger.info(f'[{tag}] {_line}')

    @async_retry(max_attempts=2, delay=1.0)
    async def _step(self, messages: List[Message],
                    tag: str) -> List[Message]:  # type: ignore
        """
        Execute a single step in the agent's interaction loop.

        This method performs the following operations in sequence:
        1. Deep copies the current message history to avoid mutation issues.
        2. Refines memory based on the current conversation state.
        3. Updates the execution plan if a planner is configured.
        4. Triggers pre-response callbacks.
        5. Generates a response from the LLM using available tools.
        6. Optionally streams the response output to stdout.
        7. Triggers post-response callbacks.
        8. Handles parallel tool calls if needed.
        9. Triggers post-tool-call callbacks.
        10. Returns the updated message history.

        The step may be retried up to two times on failure due to the `@async_retry` decorator.

        Args:
            messages (List[Message]): Current message history.
            tag (str): Identifier for logging purposes.

        Returns:
            List[Message]: Updated message history after this step.
        """
        messages = deepcopy(messages)
        # Refine memory
        messages = await self._refine_memory(messages)
        # Do plan
        messages = await self._update_plan(messages)
        await self._loop_callback('on_generate_response', messages)
        tools = await self.tool_manager.get_tools()
        if hasattr(self.config, 'generation_config') and getattr(
                self.config.generation_config, 'stream', False):
            self._log_output('[assistant]:', tag=tag)
            _content = ''
            is_first = True
            for _response_message in self._handle_stream_message(
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
                self._log_output('[assistant]:', tag=tag)
                self._log_output(_response_message.content, tag=tag)
        if _response_message.tool_calls:
            self._log_output('[tool_calling]:', tag=tag)
            for tool_call in _response_message.tool_calls:
                tool_call = deepcopy(tool_call)
                if isinstance(tool_call['arguments'], str):
                    tool_call['arguments'] = json.loads(tool_call['arguments'])
                self._log_output(
                    json.dumps(tool_call, ensure_ascii=False, indent=4),
                    tag=tag)

        if messages[-1] is not _response_message:
            messages.append(_response_message)
        await self._loop_callback('after_generate_response', messages)
        await self._loop_callback('on_tool_call', messages)

        if _response_message.tool_calls:
            messages = await self._parallel_tool_call(messages)
        else:
            self.runtime.should_stop = True
        await self._loop_callback('after_tool_call', messages)
        self._log_output(
            f'[usage] prompt_tokens: {_response_message.prompt_tokens}, '
            f'completion_tokens: {_response_message.completion_tokens}',
            tag=tag)
        yield messages

    def _prepare_llm(self):
        """Initialize the LLM model from the configuration."""
        self.llm: LLM = LLM.from_config(self.config)

    def _prepare_runtime(self):
        """Initialize the runtime context."""
        self.runtime: Runtime = Runtime(llm=self.llm)

    def _read_history(self, messages: List[Message],
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
        if not query or not self.load_cache or not self.task:
            return self.config, self.runtime, messages  # noqa

        config, _messages = read_history(
            getattr(self.config, 'output_dir', 'output'), task=self.task)
        if config is not None and _messages is not None:
            if hasattr(config, 'runtime'):
                runtime = Runtime(llm=self.llm)
                runtime.from_dict(config.runtime)
                delattr(config, 'runtime')
            else:
                runtime = self.runtime
            return config, runtime, _messages
        else:
            return self.config, self.runtime, messages  # noqa

    def _save_history(self, messages: List[Message], **kwargs):
        """
        Save current chat history to disk for future resuming.

        Args:
            messages (List[Message]): Current message history to save.
        """
        query = messages[1].content
        if not query or not self.task or self.task == 'subtask':
            return
        config: DictConfig = deepcopy(self.config)  # noqa
        config.runtime = self.runtime.to_dict()
        save_history(
            getattr(config, 'output_dir', 'output'),
            task=self.task,
            config=config,
            messages=messages)

    async def _run(self, messages: Union[List[Message], str], **kwargs):
        """Run the agent, mainly contains a llm calling and tool calling loop.

        Args:
            messages (Union[List[Message], str]): Input data for the agent. Can be a raw string prompt,
                                               or a list of previous interaction messages.
            **kwargs: Additional runtime arguments.

        Returns:
            List[Message]: A list of message objects representing the agent's response or interaction history.
        """
        try:
            self.max_chat_round = getattr(self.config, 'max_chat_round', 20)
            self._register_callback_from_config()
            self._prepare_llm()
            self._prepare_runtime()
            await self._prepare_tools()
            await self._prepare_memory()
            await self._prepare_planer()
            await self._prepare_rag()
            self.runtime.tag = self.tag

            self.config, self.runtime, messages = self._read_history(
                messages, **kwargs)

            if self.runtime.round == 0:
                # 0 means no history
                messages = await self._prepare_messages(messages)
                await self._loop_callback('on_task_begin', messages)
                if self.planer:
                    messages = await self.planer.make_plan(
                        self.runtime, messages)

            for message in messages:
                if message.role != 'system':
                    self._log_output('[' + message.role + ']:', tag=self.tag)
                    self._log_output(message.content, tag=self.tag)
            while not self.runtime.should_stop:
                yield_step = self._step(messages, self.tag)
                async for messages in yield_step:
                    yield messages
                self.runtime.round += 1
                # +1 means the next round the assistant may give a conclusion
                if self.runtime.round >= self.max_chat_round + 1:
                    if not self.runtime.should_stop:
                        messages.append(
                            Message(
                                role='assistant',
                                content=
                                f'Task {messages[1].content} failed, max round({self.max_chat_round}) exceeded.'
                            ))
                    self.runtime.should_stop = True
                    yield messages
                # save history
                self._save_history(messages, **kwargs)

            await self._loop_callback('on_task_end', messages)
            await self._cleanup_tools()
        except Exception as e:
            if hasattr(self.config, 'help'):
                logger.error(
                    f'[{self.tag}] Runtime error, please follow the instructions:\n\n {self.config.help}'
                )
            raise e

    async def run(self, messages: Union[List[Message], str],
                  **kwargs) -> List[Message]:
        stream = kwargs.get('stream', False)
        if stream:
            OmegaConf.update(
                self.config, 'generation_config.stream', True, merge=True)

        if stream:

            async def stream_generator():
                async for chunk in self._run(messages=messages, **kwargs):
                    yield chunk

            return stream_generator()
        else:
            res = None
            async for chunk in self._run(messages=messages, **kwargs):
                res = chunk
            return res
