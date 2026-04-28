# Copyright (c) ModelScope Contributors. All rights reserved.
import inspect
import json
from copy import deepcopy
from typing import Any, Dict, Generator, Iterable, List, Optional

import httpx
from omegaconf import DictConfig, OmegaConf
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

from ms_agent.llm import LLM
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.utils import MAX_CONTINUE_RUNS, assert_package_exist, get_logger, retry
from ms_agent.utils.constants import get_service_config

logger = get_logger()


class _DashScopeResponsesTransport(httpx.HTTPTransport):
    """Rewrite /v1/responses -> /v1/chat/completions for DashScope proxy.

    DashScope serves the OpenAI Responses protocol on the chat/completions
    path rather than the standard /v1/responses path.  This transport
    transparently rewrites the SDK's outgoing request so that
    ``client.responses.create()`` hits the correct DashScope endpoint.
    """

    def handle_request(self, request):
        if b'/v1/responses' in request.url.raw_path:
            new_path = request.url.raw_path.replace(b'/v1/responses', b'/v1/chat/completions')
            request.url = request.url.copy_with(raw_path=new_path)
        return super().handle_request(request)


class OpenAI(LLM):
    """Base Class for OpenAI SDK LLMs.

    This class provides the base implementation for interacting with OpenAI-compatible models,
    including support for chat completions, streaming responses, and continue generates.

    Supports the OpenAI Responses API (``client.responses.create``) when
    ``generation_config.use_responses_api`` is ``true``.  In this mode,
    reasoning summaries are extracted and surfaced through
    ``Message.reasoning_content`` so the agent's existing thinking display
    works without change.

    Args:
        config (`DictConfig`): The configuration object containing model and generation settings.
        base_url (`Optional[str]`): Custom base URL for the API endpoint. Defaults to None.
        api_key (`Optional[str]`): Authentication key for the API. Defaults to None.
    """

    input_msg = {'role', 'content', 'tool_calls', 'partial', 'prefix', 'tool_call_id'}

    # Providers that support cache_control in structured content blocks
    CACHE_CONTROL_PROVIDERS = ['dashscope', 'anthropic']

    def __init__(
        self,
        config: DictConfig,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        super().__init__(config)
        assert_package_exist('openai')
        import openai

        self.model: str = config.llm.model
        self.max_continue_runs = getattr(config.llm, 'max_continue_runs', None) or MAX_CONTINUE_RUNS
        base_url = base_url or getattr(config.llm, 'openai_base_url', None) or get_service_config('openai').base_url
        api_key = api_key or getattr(config.llm, 'openai_api_key', None)

        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.base_url = base_url or ''
        self.args: Dict = OmegaConf.to_container(getattr(config, 'generation_config', DictConfig({})))

        # Responses API support
        self._use_responses_api = bool(self.args.get('use_responses_api', False))
        self._responses_client = None
        self._responses_state_mode = str(self.args.get('responses_state_mode', 'stateless')).lower()
        if self._responses_state_mode == 'stateful':
            self._responses_state_mode = 'previous_response_id'

        if self._use_responses_api:
            self._is_dashscope = bool(base_url and 'dashscope' in base_url.lower())
            if self._is_dashscope:
                http_client = httpx.Client(
                    transport=_DashScopeResponsesTransport(),
                    timeout=httpx.Timeout(300.0, connect=60.0),
                )
                self._responses_client = openai.OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                )
            else:
                self._responses_client = self.client

        # Prefix cache configuration
        # - force_prefix_cache: enable structured content with cache_control for explicit caching
        # - prefix_cache_roles: which messages to cache (only these are converted to structured format)
        #   Supports:
        #     - Role names: 'system', 'user', 'assistant', 'tool'
        #     - Special values: 'last_message' (only cache the last message in the list)
        #   Default: ['system'] - system prompt is usually the longest stable prefix
        self._prefix_cache_enabled = self.args.get('force_prefix_cache', False)
        self._prefix_cache_roles = set(self.args.get('prefix_cache_roles', ['system']))
        self._prefix_cache_provider = self._detect_cache_provider()

    def _detect_cache_provider(self) -> Optional[str]:
        """
        Detect which provider-specific cache_control format to use based on base_url.

        Returns:
            Provider name (e.g. 'dashscope', 'anthropic') or None for native OpenAI
            (which uses automatic prefix caching without explicit cache_control).
        """
        if not self._prefix_cache_enabled:
            return None
        base_url_lower = self.base_url.lower()
        for provider in self.CACHE_CONTROL_PROVIDERS:
            if provider in base_url_lower:
                return provider
        # Native OpenAI: automatic prefix caching, no need for cache_control
        return None

    @staticmethod
    def _to_structured_content(
        content: Any,
        add_cache_control: bool = False,
        provider: Optional[str] = None,
    ) -> Any:
        """
        Convert message content to structured content blocks for prefix caching.

        This method is idempotent: already-structured content is returned as-is
        (with optional cache_control addition for dashscope/anthropic).

        Args:
            content: Original content (str or list)
            add_cache_control: Whether to add cache_control to text blocks

        Returns:
            Structured content list or original content if not applicable
        """
        if not add_cache_control:
            return content

        # Case 1: plain string -> wrap in structured block
        if isinstance(content, str):
            block: Dict[str, Any] = {'type': 'text', 'text': content}
            if provider in {'dashscope', 'anthropic'}:
                block['cache_control'] = {'type': 'ephemeral'}
            return [block]

        # Case 2: already a list (multimodal or pre-structured)
        if isinstance(content, list):
            # Add cache_control to text blocks that don't have it
            new_list = []
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text' and 'cache_control' not in item:
                    new_item = dict(item)
                    new_item['cache_control'] = {'type': 'ephemeral'}
                    new_list.append(new_item)
                else:
                    new_list.append(item)
            return new_list

        # Other types: return as-is
        return content

    def format_tools(self, tools: Optional[List[Tool]] = None) -> List[Dict[str, Any]]:
        """Formats a list of tools into the structure expected by the OpenAI API.

        If server_name is present in a tool, it will be used as a prefix for the function name.

        Args:
            tools (`Optional[List[Tool]]`): A list of Tool objects to format.

        Returns:
            List[Dict[str, Any]]: A list of formatted tool definitions suitable for OpenAI API.
        """
        if tools:
            tools = [
                {
                    'type': 'function',
                    'function': {
                        'name': tool['tool_name'],
                        'description': tool['description'],
                        'parameters': tool['parameters'],
                    },
                }
                for tool in tools
            ]
        else:
            tools = None
        return tools

    @retry(max_attempts=LLM.retry_count, delay=1.0)
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        max_continue_runs: Optional[int] = None,
        **kwargs,
    ) -> Message | Generator[Message, None, None]:
        """Generates a response based on the given conversation history and optional tools.

        Args:
            messages (`List[Message]`): The conversation history.
            tools (`Optional[List[Tool]]`): Optional list of available functions/tools.
            **kwargs: Additional parameters passed to the model.

        Returns:
            Union[Message, Generator[Message, None, None]]: Either a single Message object (non-streaming)
                or a generator yielding Message chunks (streaming).
        """
        args = self.args.copy()
        args.update(kwargs)
        stream = args.get('stream', False)

        if self._use_responses_api:
            if stream:
                return self._responses_stream_generate(messages, tools, **args)
            else:
                return self._responses_generate(messages, tools, **args)

        parameters = inspect.signature(self.client.chat.completions.create).parameters
        args = {key: value for key, value in args.items() if key in parameters}
        completion = self._call_llm(messages, self.format_tools(tools), **args)

        max_continue_runs = max_continue_runs or self.max_continue_runs
        if stream:
            return self._stream_continue_generate(messages, completion, tools, max_continue_runs - 1, **args)
        else:
            return self._continue_generate(messages, completion, tools, max_continue_runs - 1, **args)

    def _call_llm(self, messages: List[Message], tools: Optional[List[Tool]] = None, **kwargs) -> Any:
        """Calls the OpenAI chat completion API with the provided messages and tools.

        Args:
            messages (`List[Message]`): Formatted message history.
            tools (`Optional[List[Tool]]`): Optional list of tools to use.
            **kwargs: Additional parameters for the API call.

        Returns:
            Any: Raw output from the OpenAI chat completion API.
        """
        messages = self._format_input_message(messages)

        is_streaming = kwargs.get('stream', False)
        stream_options_config = self.args.get('stream_options', {})
        # For streaming responses, we should request usage statistics by default,
        # unless it's explicitly disabled in the configuration.
        if is_streaming and stream_options_config.get('include_usage', True):
            kwargs.setdefault('stream_options', {})['include_usage'] = True

        return self.client.chat.completions.create(model=self.model, messages=messages, tools=tools, **kwargs)

    @staticmethod
    def _extract_cache_info(usage_obj: Any) -> tuple:
        """
        Extract cache info from an OpenAI-compatible usage object.

        Returns:
            tuple: (cached_tokens, cache_creation_input_tokens)
            - cached_tokens: tokens that hit existing cache
            - cache_creation_input_tokens: tokens used to create new cache (explicit cache only)

        OpenAI/DashScope format: usage.prompt_tokens_details.{cached_tokens, cache_creation_input_tokens}
        """
        if not usage_obj:
            return 0, 0
        details = getattr(usage_obj, 'prompt_tokens_details', None)
        if details is None and isinstance(usage_obj, dict):
            details = usage_obj.get('prompt_tokens_details')
        if details is None:
            return 0, 0
        if isinstance(details, dict):
            cached = int(details.get('cached_tokens', 0) or 0)
            created = int(details.get('cache_creation_input_tokens', 0) or 0)
        else:
            cached = int(getattr(details, 'cached_tokens', 0) or 0)
            created = int(getattr(details, 'cache_creation_input_tokens', 0) or 0)
        return cached, created

    def _merge_stream_message(self, pre_message_chunk: Optional[Message], message_chunk: Message) -> Optional[Message]:
        """Merges a new chunk of message into the previous chunks during streaming.

        Used to accumulate partial results into a complete Message object.

        Args:
            pre_message_chunk (`Optional[Message]`): Previously accumulated message chunk.
            message_chunk (`Message`): New message chunk to merge.

        Returns:
            Optional[Message]: Merged message with updated content and tool calls.

        Note:
            - **Content Merging**: Textual content (`content`, `reasoning_content`) is appended cumulatively.
            - **Tool Call Merging**: If the same tool call index appears in consecutive chunks,
              its `arguments` and `tool_name` will be updated incrementally.
            - If a new tool call index is found, it will be added as a new entry in `tool_calls`.
        """
        if not pre_message_chunk:
            return message_chunk
        message = deepcopy(pre_message_chunk)
        message.reasoning_content += message_chunk.reasoning_content
        message.content += message_chunk.content
        if message_chunk.tool_calls:
            if message.tool_calls:
                if message.tool_calls[-1]['index'] == message_chunk.tool_calls[0]['index']:
                    if message_chunk.tool_calls[0]['id']:
                        message.tool_calls[-1]['id'] = message_chunk.tool_calls[0]['id']
                    if message_chunk.tool_calls[0]['arguments']:
                        if message.tool_calls[-1]['arguments']:
                            message.tool_calls[-1]['arguments'] += message_chunk.tool_calls[0]['arguments']
                        else:
                            # message.tool_calls[-1]['arguments'] may be None
                            message.tool_calls[-1]['arguments'] = message_chunk.tool_calls[0]['arguments']
                    if message_chunk.tool_calls[0]['tool_name']:
                        message.tool_calls[-1]['tool_name'] = message_chunk.tool_calls[0]['tool_name']
                else:
                    message.tool_calls.append(
                        ToolCall(
                            id=message_chunk.tool_calls[0]['id'],
                            arguments=message_chunk.tool_calls[0]['arguments'],
                            type='function',
                            tool_name=message_chunk.tool_calls[0]['tool_name'],
                            index=message_chunk.tool_calls[0]['index'],
                        )
                    )
            else:
                message.tool_calls = message_chunk.tool_calls
        return message

    def _stream_continue_generate(
        self,
        messages: List[Message],
        completion: Iterable,
        tools: Optional[List[Tool]] = None,
        max_runs: Optional[int] = None,
        **kwargs,
    ) -> Generator[Message, None, None]:
        """Recursively continues generating until the model finishes naturally in streaming mode.

        Args:
            messages(`List[Message]`): The previous messages.
            completion(`Iterable`): Iterable of streaming output messages, usually comes from the output of `call_llm`
            tools(`Optional[List[Tool]]`): List of tools to use.
            **kwargs: Extra generation kwargs.

        Yields:
            Message: Incremental chunks of the generated message.
        """
        message = None
        for chunk in completion:
            message_chunk = self._stream_format_output_message(chunk)
            message = self._merge_stream_message(message, message_chunk)
            # chunk[-2]: chunk with finish_reason and last contents
            # chunk[-1]: chunk with usage only
            if chunk.choices and chunk.choices[0].finish_reason:
                try:
                    next_chunk = next(completion)
                    message.prompt_tokens += next_chunk.usage.prompt_tokens
                    cached, created = self._extract_cache_info(getattr(next_chunk, 'usage', None))
                    message.cached_tokens += cached
                    message.cache_creation_input_tokens += created
                    message.completion_tokens += next_chunk.usage.completion_tokens
                except (StopIteration, AttributeError):
                    # The stream may end without a final usage chunk, which is acceptable.
                    pass
                first_run = not messages[-1].to_dict().get('partial', False)
                if chunk.choices[0].finish_reason in ['length', 'null'] and (max_runs is None or max_runs != 0):
                    logger.info(f'finish_reason: {chunk.choices[0].finish_reason}, continue generate.')
                    completion = self._call_llm_for_continue_gen(messages, message, tools, **kwargs)
                    for chunk in self._stream_continue_generate(
                        messages, completion, tools, max_runs - 1 if max_runs is not None else None, **kwargs
                    ):
                        if first_run:
                            yield self._merge_stream_message(messages[-1], chunk)
                        else:
                            yield chunk
                elif not first_run:
                    self._merge_partial_message(messages, message)
                    messages[-1].partial = False
                    message = messages[-1]

            yield message

    @staticmethod
    def _stream_format_output_message(completion_chunk) -> Message:
        """Formats a single chunk from the streaming response into a Message object.

        Args:
            completion_chunk: A single item from the streamed response.

        Returns:
            Message: A Message object representing the current chunk.
        """
        tool_calls = None
        reasoning_content = ''
        content = ''
        if completion_chunk.choices and completion_chunk.choices[0].delta:
            content = completion_chunk.choices[0].delta.content
            reasoning_content = getattr(completion_chunk.choices[0].delta, 'reasoning_content', '')
            if completion_chunk.choices[0].delta.tool_calls:
                func = completion_chunk.choices[0].delta.tool_calls
                tool_calls = [
                    ToolCall(
                        id=tool_call.id,
                        index=tool_call.index,
                        type=tool_call.type,
                        arguments=tool_call.function.arguments,
                        tool_name=tool_call.function.name,
                    )
                    for tool_call in func
                ]
        content = content or ''
        reasoning_content = reasoning_content or ''
        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            id=completion_chunk.id,
            prompt_tokens=getattr(completion_chunk.usage, 'prompt_tokens', 0),
            completion_tokens=getattr(completion_chunk.usage, 'completion_tokens', 0),
        )

    @staticmethod
    def _format_output_message(completion) -> Message:
        """Formats the full non-streaming response into a Message object.

        Args:
            completion: The raw response from the OpenAI API.

        Returns:
            Message: A Message object containing the final response.
        """
        content = completion.choices[0].message.content or ''
        if hasattr(completion.choices[0].message, 'reasoning_content'):
            reasoning_content = completion.choices[0].message.reasoning_content or ''
        else:
            reasoning_content = ''
        tool_calls = None
        if completion.choices[0].message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tool_call.id,
                    index=getattr(tool_call, 'index', idx),
                    type=tool_call.type,
                    arguments=tool_call.function.arguments,
                    tool_name=tool_call.function.name,
                )
                for idx, tool_call in enumerate(completion.choices[0].message.tool_calls)
            ]
        cached, created = OpenAI._extract_cache_info(getattr(completion, 'usage', None))
        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
            id=completion.id,
            prompt_tokens=completion.usage.prompt_tokens,
            cached_tokens=cached,
            cache_creation_input_tokens=created,
            completion_tokens=completion.usage.completion_tokens,
        )

    @staticmethod
    def _merge_partial_message(messages: List[Message], new_message: Message):
        """Merges a partial message into the last message in the message list.

        Args:
            messages (`List[Message]`): Current list of messages.
            new_message (`Message`): Partial message to merge.
        """
        messages[-1].reasoning_content += new_message.reasoning_content
        messages[-1].content += new_message.content
        messages[-1].prompt_tokens += new_message.prompt_tokens
        messages[-1].cached_tokens += new_message.cached_tokens
        messages[-1].cache_creation_input_tokens += new_message.cache_creation_input_tokens
        messages[-1].completion_tokens += new_message.completion_tokens
        if new_message.tool_calls:
            if messages[-1].tool_calls:
                messages[-1].tool_calls += new_message.tool_calls
            else:
                messages[-1].tool_calls = new_message.tool_calls

    def _call_llm_for_continue_gen(
        self, messages: List[Message], new_message: Message, tools: List[Tool] = None, **kwargs
    ) -> Any:
        """Prepares and calls the LLM for continuation when the response is unfinished.

        If the previous message marked as unfinished, it will be updated with the new content.
        Otherwise, a new message marked as unfinished will be added to the message list.

        Args:
            messages (`List[Message]`): Current list of conversation messages.
            new_message (`Message`): The newly generated partial message.
            tools (`List[Tool]`, optional): Available functions or tools.
            **kwargs: Additional generation parameters passed to the LLM.

        Returns:
            Any: The raw output from the LLM API call (e.g., chat completion object).
        """
        # ref: https://bailian.console.aliyun.com/?tab=doc#/doc/?type=model&url=https%3A%2F%2Fhelp.aliyun.com%2Fdocument_detail%2F2862210.html&renderType=iframe # noqa
        # TODO: Move to dashscope_llm and find a proper continue way for openai_llm generating
        if messages[-1].to_dict().get('partial', False):
            self._merge_partial_message(messages, new_message)
        else:
            # In platforms Bailian, setting `message.partial = True` indicates that the message
            #         is not yet complete and may be continued in the next generation step.
            if messages[-1].content != new_message.content:
                messages.append(new_message)
            messages[-1].partial = True
        messages[-1].api_calls += 1

        return self._call_llm(messages, tools, **kwargs)

    def _continue_generate(
        self, messages: List[Message], completion, tools: List[Tool] = None, max_runs: Optional[int] = None, **kwargs
    ) -> Message:
        """Recursively continues generating until the model finishes naturally.

        This method checks whether the generation was stopped due to length limitations,
        and if so, triggers another call to the LLM using the accumulated context.

        Args:
            messages (`List[Message]`): The current conversation history.
            completion (`Any`): Initial or intermediate response from the LLM.
            tools (`List[Tool]`, optional): Optional list of available tools.
            **kwargs: Additional parameters used in generation.

        Returns:
            Message: A fully formed Message object containing the complete response.
        """
        new_message = self._format_output_message(completion)
        if completion.choices[0].finish_reason in ['length', 'null'] and (max_runs is None or max_runs != 0):
            logger.info(f'finish_reason: {completion.choices[0].finish_reason}， continue generate.')
            completion = self._call_llm_for_continue_gen(messages, new_message, tools, **kwargs)
            return self._continue_generate(
                messages, completion, tools, max_runs - 1 if max_runs is not None else None, **kwargs
            )
        elif messages[-1].to_dict().get('partial', False):
            self._merge_partial_message(messages, new_message)
            messages[-1].partial = False
            return messages.pop(-1)
        else:
            return new_message

    def _build_responses_input(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert internal Message list to the ``input`` format expected by
        the Responses API.

        Key differences from chat completions format:
          - ``system`` role becomes ``developer``.
          - ``assistant`` messages with ``tool_calls`` emit the text content
            as a normal assistant item, followed by one ``function_call``
            item per tool call.
          - ``tool`` role messages become ``function_call_output`` items
            (keyed by ``call_id``, not ``role``).
        """
        items: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.role == 'system':
                items.append(
                    {
                        'role': 'developer',
                        'content': msg.content,
                    }
                )
            elif msg.role == 'assistant':
                if self._responses_state_mode != 'previous_response_id':
                    # Stateless mode needs explicit passback of opaque reasoning
                    # items returned by the previous response.
                    for raw_item in getattr(msg, '_responses_output_items', []):
                        items.append(raw_item)
                if msg.content and not self._is_responses_tool_placeholder(msg):
                    items.append(
                        {
                            'role': 'assistant',
                            'content': msg.content,
                        }
                    )
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        arguments = tc.get('arguments', '{}')
                        if not isinstance(arguments, str):
                            arguments = json.dumps(arguments, ensure_ascii=False)
                        items.append(
                            {
                                'type': 'function_call',
                                'call_id': tc.get('id', ''),
                                'name': tc.get('tool_name', ''),
                                'arguments': arguments,
                            }
                        )
            elif msg.role == 'tool':
                content = msg.content
                if not isinstance(content, str):
                    content = json.dumps(content, ensure_ascii=False)
                items.append(
                    {
                        'type': 'function_call_output',
                        'call_id': msg.tool_call_id or '',
                        'output': content,
                    }
                )
            else:
                items.append(
                    {
                        'role': msg.role,
                        'content': msg.content,
                    }
                )
        return items

    @staticmethod
    def _is_responses_tool_placeholder(message: Message) -> bool:
        """Return True for framework-generated assistant placeholder text."""
        return bool(message.tool_calls) and message.content == 'Let me do a tool calling.'

    def _prepare_responses_request(
        self, messages: List[Message], args: Dict[str, Any]
    ) -> tuple[List[Message], Dict[str, Any]]:
        """Prepare message slice and request args for Responses API calls."""
        request_args = dict(args)

        if self._responses_state_mode != 'previous_response_id':
            return messages, request_args

        if request_args.get('previous_response_id'):
            return messages, request_args

        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.role == 'assistant' and msg.id:
                request_args['previous_response_id'] = msg.id
                return messages[idx + 1 :], request_args

        return messages, request_args

    def _build_responses_tools(self, tools: Optional[List[Tool]]) -> Optional[List[Dict[str, Any]]]:
        """Convert internal Tool list to Responses API function tool format."""
        if not tools:
            return None
        return [
            {
                'type': 'function',
                'name': t['tool_name'],
                'description': t.get('description', ''),
                'parameters': t.get('parameters', {}),
            }
            for t in tools
        ]

    def _build_responses_kwargs(self, args: Dict) -> Dict:
        """Filter and reshape generation args for ``responses.create``."""
        kwargs: Dict[str, Any] = {}

        reasoning_effort = args.get('reasoning_effort')
        reasoning_summary = args.get('reasoning_summary', 'auto')
        if reasoning_effort or reasoning_summary:
            reasoning: Dict[str, Any] = {}
            if reasoning_effort:
                reasoning['effort'] = reasoning_effort
            if reasoning_summary:
                reasoning['summary'] = reasoning_summary
            kwargs['reasoning'] = reasoning

        if args.get('temperature') is not None:
            kwargs['temperature'] = args['temperature']
        if args.get('top_p') is not None:
            kwargs['top_p'] = args['top_p']
        if args.get('max_output_tokens') is not None:
            kwargs['max_output_tokens'] = args['max_output_tokens']
        if args.get('stream_options') is not None:
            kwargs['stream_options'] = args['stream_options']
        if args.get('previous_response_id') is not None:
            kwargs['previous_response_id'] = args['previous_response_id']

        include = args.get('include')
        if include is not None:
            kwargs['include'] = include
        elif self._responses_state_mode != 'previous_response_id':
            # Stateless multi-turn mode needs encrypted reasoning so opaque
            # reasoning items can be passed back in subsequent requests.
            kwargs['include'] = ['reasoning.encrypted_content']

        return kwargs

    @staticmethod
    def _extract_reasoning_summaries_from_response(response) -> str:
        """Pull reasoning summary text from a completed Responses API object."""
        parts: List[str] = []
        for item in getattr(response, 'output', []) or []:
            if getattr(item, 'type', None) == 'reasoning':
                for summary in getattr(item, 'summary', []) or []:
                    text = getattr(summary, 'text', None)
                    if text:
                        parts.append(text)
        return '\n'.join(parts)

    @staticmethod
    def _extract_tool_calls_from_response(response) -> Optional[List[ToolCall]]:
        """Extract tool calls from a completed Responses API object."""
        tool_calls: List[ToolCall] = []
        for item in getattr(response, 'output', []) or []:
            if getattr(item, 'type', None) == 'function_call':
                arguments = getattr(item, 'arguments', '{}')
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments, ensure_ascii=False)
                tool_calls.append(
                    ToolCall(
                        id=getattr(item, 'call_id', '') or getattr(item, 'id', ''),
                        index=len(tool_calls),
                        type='function',
                        tool_name=getattr(item, 'name', ''),
                        arguments=arguments,
                    )
                )
        return tool_calls if tool_calls else None

    @staticmethod
    def _extract_usage_from_response(response) -> tuple:
        """Return (prompt_tokens, completion_tokens) from a Responses API object."""
        usage = getattr(response, 'usage', None)
        if usage is None:
            return 0, 0
        return (
            getattr(usage, 'input_tokens', 0) or 0,
            getattr(usage, 'output_tokens', 0) or 0,
        )

    @staticmethod
    def _to_jsonable(value: Any) -> Any:
        """Convert SDK objects nested in Responses items into JSON-safe data."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [OpenAI._to_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {key: OpenAI._to_jsonable(item) for key, item in value.items()}
        if hasattr(value, 'model_dump'):
            return OpenAI._to_jsonable(value.model_dump())
        if hasattr(value, 'to_dict'):
            return OpenAI._to_jsonable(value.to_dict())
        return value

    def _collect_passback_items(self, response) -> List[Dict[str, Any]]:
        """Collect output items that must be passed back in multi-turn calls.

        Per OpenAI docs, reasoning items returned alongside tool calls must be
        included in the next request for reasoning models.
        """
        items: List[Dict[str, Any]] = []
        for item in getattr(response, 'output', []) or []:
            item_type = getattr(item, 'type', None)
            if item_type == 'reasoning':
                passback_item: Dict[str, Any] = {
                    'type': 'reasoning',
                    'summary': self._to_jsonable(getattr(item, 'summary', []) or []),
                }
                encrypted_content = getattr(item, 'encrypted_content', None)
                if encrypted_content:
                    passback_item['encrypted_content'] = encrypted_content
                if not getattr(self, '_is_dashscope', False):
                    item_id = getattr(item, 'id', None)
                    if item_id:
                        passback_item['id'] = item_id
                items.append(passback_item)
        return items

    def _responses_generate(self, messages: List[Message], tools: Optional[List[Tool]] = None, **args) -> Message:
        """Non-streaming Responses API call."""
        request_messages, request_args = self._prepare_responses_request(messages, args)
        input_items = self._build_responses_input(request_messages)
        resp_tools = self._build_responses_tools(tools)
        kwargs = self._build_responses_kwargs(request_args)
        if resp_tools:
            kwargs['tools'] = resp_tools

        response = self._responses_client.responses.create(
            model=self.model,
            input=input_items,
            **kwargs,
        )
        text = getattr(response, 'output_text', '') or ''
        reasoning = self._extract_reasoning_summaries_from_response(response)
        resp_tool_calls = self._extract_tool_calls_from_response(response)
        prompt_tokens, completion_tokens = self._extract_usage_from_response(response)
        passback = self._collect_passback_items(response)

        return Message(
            role='assistant',
            content=text,
            reasoning_content=reasoning,
            tool_calls=resp_tool_calls,
            _responses_output_items=passback,
            id=getattr(response, 'id', ''),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    @staticmethod
    def _extract_reasoning_from_item(item) -> str:
        """Extract reasoning summary text from a single output item."""
        parts: List[str] = []
        for summary in getattr(item, 'summary', []) or []:
            text = getattr(summary, 'text', None)
            if text:
                parts.append(text)
        return '\n'.join(parts)

    def _responses_stream_generate(
        self, messages: List[Message], tools: Optional[List[Tool]] = None, **args
    ) -> Generator[Message, None, None]:
        """Streaming Responses API call.

        Yields incremental ``Message`` objects.  Reasoning summaries are
        extracted from ``response.output_item.done`` events (type=reasoning)
        which arrive *before* the first text delta, so the agent layer can
        display the thinking header before content begins streaming.
        """
        request_messages, request_args = self._prepare_responses_request(messages, args)
        input_items = self._build_responses_input(request_messages)
        resp_tools = self._build_responses_tools(tools)
        kwargs = self._build_responses_kwargs(request_args)
        if resp_tools:
            kwargs['tools'] = resp_tools

        stream = self._responses_client.responses.create(
            model=self.model,
            input=input_items,
            stream=True,
            **kwargs,
        )

        current_message = Message(
            role='assistant',
            content='',
            reasoning_content='',
        )
        streamed_text = ''
        final_response = None
        response_error_msg = ''
        reasoning_parts: List[str] = []

        for event in stream:
            event_type = getattr(event, 'type', '')

            if event_type == 'response.output_item.done':
                item = getattr(event, 'item', None)
                if item and getattr(item, 'type', None) == 'reasoning':
                    summary_text = self._extract_reasoning_from_item(item)
                    if summary_text:
                        reasoning_parts.append(summary_text)
                        current_message.reasoning_content = '\n'.join(reasoning_parts)
                        yield current_message

            elif event_type == 'response.output_text.delta':
                delta = getattr(event, 'delta', '')
                if delta:
                    streamed_text += delta
                    current_message.content = streamed_text
                    yield current_message

            elif event_type == 'response.output_text.done':
                done_text = getattr(event, 'text', '')
                if done_text and not streamed_text:
                    streamed_text = done_text
                    current_message.content = streamed_text
                    yield current_message

            elif event_type == 'response.completed':
                final_response = getattr(event, 'response', None)

            elif event_type == 'response.failed':
                failed_response = getattr(event, 'response', None)
                failed_error = getattr(failed_response, 'error', None)
                response_error_msg = getattr(failed_error, 'message', '') or str(failed_error)

        if final_response:
            if not reasoning_parts:
                reasoning = self._extract_reasoning_summaries_from_response(final_response)
                if reasoning:
                    current_message.reasoning_content = reasoning
            resp_tool_calls = self._extract_tool_calls_from_response(final_response)
            if resp_tool_calls:
                current_message.tool_calls = resp_tool_calls
            passback = self._collect_passback_items(final_response)
            if passback:
                current_message._responses_output_items = passback
            prompt_tokens, completion_tokens = self._extract_usage_from_response(final_response)
            current_message.prompt_tokens = prompt_tokens
            current_message.completion_tokens = completion_tokens
            current_message.id = getattr(final_response, 'id', '')
            yield current_message
        elif response_error_msg:
            logger.error(f'Responses API failed: {response_error_msg}')
            raise RuntimeError(f'Responses API call failed: {response_error_msg}')

    def _format_input_message(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Converts a list of Message objects into the format expected by the OpenAI API.

        Args:
            messages (`List[Message]`): List of Message objects.

        Returns:
            List[Dict[str, Any]]: List of dictionaries compatible with OpenAI's input format.
        """
        # Determine if we need to add cache_control (for dashscope/anthropic)
        add_cache_control = self._prefix_cache_provider is not None

        # Determine which message index should have cache_control (the last matching one)
        cache_indice = None
        if self._prefix_cache_enabled and add_cache_control:
            cache_indices = set()
            # Check for 'last_message' special value
            if 'last_message' in self._prefix_cache_roles and messages:
                cache_indices.add(len(messages) - 1)
            # Check for role-based caching
            role_cache = self._prefix_cache_roles - {'last_message'}
            for idx, msg in enumerate(messages):
                msg_role = msg.role if isinstance(msg, Message) else msg.get('role', '')
                if msg_role in role_cache:
                    cache_indices.add(idx)
            cache_indice = max(cache_indices) if cache_indices else None

        openai_messages = []
        for idx, message in enumerate(messages):
            if isinstance(message, Message):
                # Only strip string content, keep list content as-is for multimodal
                if isinstance(message.content, str):
                    message.content = message.content.strip()
                message = message.to_dict_clean()
            else:
                message = dict(message)

            content = message.get('content', '')
            # Only strip string content, multimodal content (list) should be kept as-is
            if isinstance(content, str):
                content = content.strip()

            # Apply prefix cache structured content transformation
            # Only for string content, multimodal content is already structured
            if cache_indice is not None and idx == cache_indice:
                content = self._to_structured_content(
                    content, add_cache_control=True, provider=self._prefix_cache_provider
                )

            # Build the message dict, handling both string and multimodal content
            formatted_message = {}
            for key, value in message.items():
                if key in self.input_msg:
                    # Only strip string values, keep other types as-is
                    if isinstance(value, str):
                        formatted_message[key] = value.strip() if value else ''
                    else:
                        formatted_message[key] = value

            # Always use the transformed content to support features like prefix caching
            # The content variable has been processed by _to_structured_content() if needed
            formatted_message['content'] = content

            openai_messages.append(formatted_message)

        return openai_messages
