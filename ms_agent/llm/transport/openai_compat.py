# Copyright (c) ModelScope Contributors. All rights reserved.
"""OpenAI Chat Completions compatible transport.

Faithful port of the proven ``OpenAI`` engine (``ms_agent/llm/openai_llm.py``)
into the data-driven provider layer. Covers OpenAI, ModelScope, DashScope,
DeepSeek, Google (Gemini OpenAI-compat), Zhipu, MiniMax, OpenRouter and any
other OpenAI-compatible endpoint.

Provider differences that used to require subclasses are now parameters:
  * ``continue_gen_mode``: 'partial' (DashScope/Bailian) | 'prefix' (DeepSeek)
  * ``continue_gen_stop``: extra stop sequences for prefix-mode continuation
  * prefix caching: driven by ``force_prefix_cache`` in generation_config

Behavioral contract preserved (see plan §10): continue-generation (stream and
non-stream), stream chunk merging, partial/prefix message back-fill, prefix
cache structured content, usage extraction (cache/reasoning tokens), cross-run
usage accumulation, and ``input_msg`` field filtering.
"""
from __future__ import annotations

import inspect
from copy import deepcopy
from typing import Any, Dict, Generator, Iterable, List, Optional, Union

from ms_agent.llm.transport.base import Transport
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.utils import MAX_CONTINUE_RUNS, assert_package_exist, get_logger

logger = get_logger()


class OpenAICompatTransport(Transport):
    # Fields forwarded to the API. Includes continue-gen flags (partial/prefix)
    # and tool_call_id so multi-turn tool flows round-trip correctly.
    input_msg = {
        'role', 'content', 'tool_calls', 'partial', 'prefix', 'tool_call_id'
    }

    # Providers that support cache_control in structured content blocks.
    CACHE_CONTROL_PROVIDERS = ['dashscope', 'anthropic']

    def __init__(
        self,
        model: str,
        api_key: Optional[str],
        base_url: str,
        generation_config: Optional[Dict] = None,
        continue_gen_mode: Optional[str] = None,
        continue_gen_stop: Optional[List[str]] = None,
        max_continue_runs: Optional[int] = None,
        strip_reasoning_tags: bool = False,
    ):
        assert_package_exist('openai')
        import openai

        self.model = model
        self.base_url = self._normalize_base_url(base_url)
        self.client = openai.OpenAI(api_key=api_key, base_url=self.base_url)
        self.args: Dict = dict(generation_config or {})
        self.max_continue_runs = max_continue_runs or MAX_CONTINUE_RUNS
        self._strip_reasoning_tags = strip_reasoning_tags

        # Continue-generation: 'prefix' uses DeepSeek chat-prefix completion,
        # everything else (incl. DashScope) uses the 'partial' flag.
        # 'prefix' is only valid on DeepSeek's beta endpoint; downgrade to the
        # generic 'partial' continuation when not on a beta base_url so a
        # continuation doesn't 400 on the standard /v1 endpoint.
        if continue_gen_mode == 'prefix' and 'beta' not in self.base_url.lower():
            logger.info(
                'continue_gen_mode="prefix" requires a beta endpoint; '
                'falling back to "partial" continuation for %s', self.base_url)
            continue_gen_mode = None
        self.continue_gen_mode = continue_gen_mode
        self._continue_flag = 'prefix' if continue_gen_mode == 'prefix' \
            else 'partial'
        self.continue_gen_stop = list(continue_gen_stop or [])

        # Prefix cache configuration.
        self._prefix_cache_enabled = self.args.get('force_prefix_cache', False)
        self._prefix_cache_roles = set(
            self.args.get('prefix_cache_roles', ['system']))
        self._prefix_cache_provider = self._detect_cache_provider()

    @staticmethod
    def _normalize_base_url(base_url: Optional[str]) -> str:
        """Tolerate a base_url that mistakenly includes the endpoint path.

        The OpenAI SDK appends ``/chat/completions`` itself, so a configured
        base_url ending in that path would double it. Strip the suffix.
        """
        url = (base_url or '').strip()
        for suffix in ('/chat/completions/', '/chat/completions'):
            if url.endswith(suffix):
                url = url[:-len(suffix)]
                break
        return url

    # ------------------------------------------------------------------ #
    # prefix cache
    # ------------------------------------------------------------------ #
    def _detect_cache_provider(self) -> Optional[str]:
        if not self._prefix_cache_enabled:
            return None
        base_url_lower = self.base_url.lower()
        for provider in self.CACHE_CONTROL_PROVIDERS:
            if provider in base_url_lower:
                return provider
        # Native OpenAI: automatic prefix caching, no cache_control needed.
        return None

    @staticmethod
    def _to_structured_content(content: Any,
                               add_cache_control: bool = False,
                               provider: Optional[str] = None) -> Any:
        if not add_cache_control:
            return content
        if isinstance(content, str):
            block: Dict[str, Any] = {'type': 'text', 'text': content}
            if provider in {'dashscope', 'anthropic'}:
                block['cache_control'] = {'type': 'ephemeral'}
            return [block]
        if isinstance(content, list):
            new_list = []
            for item in content:
                if (isinstance(item, dict) and item.get('type') == 'text'
                        and 'cache_control' not in item):
                    new_item = dict(item)
                    new_item['cache_control'] = {'type': 'ephemeral'}
                    new_list.append(new_item)
                else:
                    new_list.append(item)
            return new_list
        return content

    # ------------------------------------------------------------------ #
    # formatting
    # ------------------------------------------------------------------ #
    def format_tools(
            self,
            tools: Optional[List[Tool]] = None) -> Optional[List[Dict]]:
        if tools:
            return [{
                'type': 'function',
                'function': {
                    'name': tool['tool_name'],
                    'description': tool['description'],
                    'parameters': tool['parameters'],
                }
            } for tool in tools]
        return None

    def _format_input_message(
            self, messages: List[Message]) -> List[Dict[str, Any]]:
        add_cache_control = self._prefix_cache_provider is not None

        cache_indice = None
        if self._prefix_cache_enabled and add_cache_control:
            cache_indices = set()
            if 'last_message' in self._prefix_cache_roles and messages:
                cache_indices.add(len(messages) - 1)
            role_cache = self._prefix_cache_roles - {'last_message'}
            for idx, msg in enumerate(messages):
                msg_role = msg.role if isinstance(msg, Message) else msg.get(
                    'role', '')
                if msg_role in role_cache:
                    cache_indices.add(idx)
            cache_indice = max(cache_indices) if cache_indices else None

        openai_messages = []
        for idx, message in enumerate(messages):
            if isinstance(message, Message):
                if isinstance(message.content, str):
                    message.content = message.content.strip()
                message = message.to_dict_clean()
            else:
                message = dict(message)

            content = message.get('content', '')
            if isinstance(content, str):
                content = content.strip()

            if cache_indice is not None and idx == cache_indice:
                content = self._to_structured_content(
                    content,
                    add_cache_control=True,
                    provider=self._prefix_cache_provider)

            formatted_message = {}
            for key, value in message.items():
                if key in self.input_msg:
                    if isinstance(value, str):
                        formatted_message[key] = value.strip() if value else ''
                    else:
                        formatted_message[key] = value
            formatted_message['content'] = content
            openai_messages.append(formatted_message)
        return openai_messages

    # ------------------------------------------------------------------ #
    # entry point
    # ------------------------------------------------------------------ #
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        max_continue_runs: Optional[int] = None,
        **kwargs,
    ) -> Union[Message, Generator[Message, None, None]]:
        parameters = inspect.signature(
            self.client.chat.completions.create).parameters
        args = self.args.copy()
        args.update(kwargs)
        stream = args.get('stream', False)
        args = {key: value for key, value in args.items() if key in parameters}

        # Format tools once and thread the formatted list through the
        # continuation chain. (Passing the raw tools into a continuation call
        # would send the internal schema to the API -> "missing field type".)
        formatted_tools = self.format_tools(tools)
        completion = self._call_llm(messages, formatted_tools, **args)

        max_continue_runs = max_continue_runs or self.max_continue_runs
        if stream:
            gen = self._stream_continue_generate(messages, completion,
                                                 formatted_tools,
                                                 max_continue_runs - 1, **args)
            return self._postprocess_stream(gen) if self._strip_reasoning_tags \
                else gen
        result = self._continue_generate(messages, completion, formatted_tools,
                                         max_continue_runs - 1, **args)
        return self._postprocess(result) if self._strip_reasoning_tags \
            else result

    # ------------------------------------------------------------------ #
    # inline <think> handling (e.g. MiniMax M-series)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split_think(content: str) -> tuple:
        """Split a leading ``<think>...</think>`` block out of content.

        Returns ``(reasoning, content)``. If the block is not yet closed
        (mid-stream), everything after ``<think>`` is treated as reasoning and
        content is empty until ``</think>`` arrives.
        """
        stripped = content.lstrip()
        if not stripped.startswith('<think>'):
            return '', content
        rest = stripped[len('<think>'):]
        end = rest.find('</think>')
        if end == -1:
            return rest, ''
        reasoning = rest[:end]
        answer = rest[end + len('</think>'):]
        return reasoning, answer.lstrip('\n')

    def _postprocess(self, message: Message) -> Message:
        if message is None or not isinstance(message.content, str):
            return message
        reasoning, content = self._split_think(message.content)
        if content != message.content:
            message.content = content
            message.reasoning_content = (message.reasoning_content
                                         or '') + reasoning
        return message

    def _postprocess_stream(
            self, gen: Generator[Message, None, None]
    ) -> Generator[Message, None, None]:
        # Operate on a copy so the streaming accumulator stays intact.
        for message in gen:
            yield self._postprocess(deepcopy(message))

    def _call_llm(self,
                  messages: List[Message],
                  tools: Optional[List[Dict]] = None,
                  **kwargs) -> Any:
        messages = self._format_input_message(messages)
        is_streaming = kwargs.get('stream', False)
        stream_options_config = self.args.get('stream_options', {})
        if is_streaming and stream_options_config.get('include_usage', True):
            kwargs.setdefault('stream_options', {})['include_usage'] = True
        return self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools, **kwargs)

    # ------------------------------------------------------------------ #
    # usage
    # ------------------------------------------------------------------ #
    @staticmethod
    def _usage_total(usage_obj: Any) -> int:
        """Token total of a usage object; -1 for None (so any real usage wins)."""
        if usage_obj is None:
            return -1
        return (getattr(usage_obj, 'prompt_tokens', 0) or 0) + \
            (getattr(usage_obj, 'completion_tokens', 0) or 0)

    @staticmethod
    def _extract_cache_info(usage_obj: Any) -> tuple:
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
            created = int(
                getattr(details, 'cache_creation_input_tokens', 0) or 0)
        return cached, created

    @staticmethod
    def _extract_reasoning_tokens(usage_obj: Any) -> int:
        if not usage_obj:
            return 0
        details = getattr(usage_obj, 'completion_tokens_details', None)
        if details is None and isinstance(usage_obj, dict):
            details = usage_obj.get('completion_tokens_details')
        if details is None:
            return 0
        if isinstance(details, dict):
            return int(details.get('reasoning_tokens', 0) or 0)
        return int(getattr(details, 'reasoning_tokens', 0) or 0)

    # ------------------------------------------------------------------ #
    # streaming
    # ------------------------------------------------------------------ #
    def _merge_stream_message(self, pre_message_chunk: Optional[Message],
                              message_chunk: Message) -> Optional[Message]:
        if not pre_message_chunk:
            return message_chunk
        message = deepcopy(pre_message_chunk)
        message.reasoning_content += message_chunk.reasoning_content
        message.content += message_chunk.content
        if message_chunk.tool_calls:
            if message.tool_calls:
                if message.tool_calls[-1]['index'] == message_chunk.tool_calls[
                        0]['index']:
                    if message_chunk.tool_calls[0]['id']:
                        message.tool_calls[-1]['id'] = message_chunk.tool_calls[
                            0]['id']
                    if message_chunk.tool_calls[0]['arguments']:
                        if message.tool_calls[-1]['arguments']:
                            message.tool_calls[-1][
                                'arguments'] += message_chunk.tool_calls[0][
                                    'arguments']
                        else:
                            message.tool_calls[-1][
                                'arguments'] = message_chunk.tool_calls[0][
                                    'arguments']
                    if message_chunk.tool_calls[0]['tool_name']:
                        message.tool_calls[-1][
                            'tool_name'] = message_chunk.tool_calls[0][
                                'tool_name']
                else:
                    message.tool_calls.append(
                        ToolCall(
                            id=message_chunk.tool_calls[0]['id'],
                            arguments=message_chunk.tool_calls[0]['arguments'],
                            type='function',
                            tool_name=message_chunk.tool_calls[0]['tool_name'],
                            index=message_chunk.tool_calls[0]['index']))
            else:
                message.tool_calls = message_chunk.tool_calls
        return message

    def _stream_continue_generate(
            self,
            messages: List[Message],
            completion: Iterable,
            tools: Optional[List[Tool]] = None,
            max_runs: Optional[int] = None,
            **kwargs) -> Generator[Message, None, None]:
        flag = self._continue_flag
        message = None
        for chunk in completion:
            message_chunk = self._stream_format_output_message(chunk)
            message = self._merge_stream_message(message, message_chunk)
            if chunk.choices and chunk.choices[0].finish_reason:
                # Usage may arrive in this finish chunk (e.g. DeepSeek) or in a
                # separate trailing usage-only chunk (OpenAI/DashScope/
                # ModelScope, whose finish chunk may carry a zeroed usage).
                # Consider both and take the one with real token counts.
                usage = getattr(chunk, 'usage', None)
                try:
                    next_chunk = next(completion)
                    trailing = getattr(next_chunk, 'usage', None)
                except (StopIteration, AttributeError):
                    trailing = None
                if self._usage_total(trailing) > self._usage_total(usage):
                    usage = trailing
                if usage is not None:
                    message.prompt_tokens += getattr(usage, 'prompt_tokens',
                                                     0) or 0
                    message.completion_tokens += getattr(
                        usage, 'completion_tokens', 0) or 0
                    cached, created = self._extract_cache_info(usage)
                    message.cached_tokens += cached
                    message.cache_creation_input_tokens += created
                    message.reasoning_tokens += self._extract_reasoning_tokens(
                        usage)
                first_run = not messages[-1].to_dict().get(flag, False)
                if chunk.choices[0].finish_reason in [
                        'length', 'null'
                ] and (max_runs is None or max_runs != 0):
                    logger.info(
                        f'finish_reason: {chunk.choices[0].finish_reason}, '
                        f'continue generate.')
                    completion = self._call_llm_for_continue_gen(
                        messages, message, tools, **kwargs)
                    for chunk in self._stream_continue_generate(
                            messages, completion, tools,
                            max_runs - 1 if max_runs is not None else None,
                            **kwargs):
                        if first_run:
                            yield self._merge_stream_message(
                                messages[-1], chunk)
                        else:
                            yield chunk
                elif not first_run:
                    self._merge_partial_message(messages, message)
                    setattr(messages[-1], flag, False)
                    message = messages[-1]
            yield message

    @staticmethod
    def _stream_format_output_message(completion_chunk) -> Message:
        tool_calls = None
        reasoning_content = ''
        content = ''
        if completion_chunk.choices and completion_chunk.choices[0].delta:
            content = completion_chunk.choices[0].delta.content
            reasoning_content = getattr(completion_chunk.choices[0].delta,
                                        'reasoning_content', '')
            if completion_chunk.choices[0].delta.tool_calls:
                func = completion_chunk.choices[0].delta.tool_calls
                tool_calls = [
                    ToolCall(
                        id=tool_call.id,
                        index=tool_call.index,
                        type=tool_call.type,
                        arguments=tool_call.function.arguments,
                        tool_name=tool_call.function.name)
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
            completion_tokens=getattr(completion_chunk.usage,
                                      'completion_tokens', 0))

    # ------------------------------------------------------------------ #
    # non-streaming + continuation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _format_output_message(completion) -> Message:
        content = completion.choices[0].message.content or ''
        if hasattr(completion.choices[0].message, 'reasoning_content'):
            reasoning_content = completion.choices[
                0].message.reasoning_content or ''
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
                    tool_name=tool_call.function.name) for idx, tool_call in
                enumerate(completion.choices[0].message.tool_calls)
            ]
        usage = getattr(completion, 'usage', None)
        cached, created = OpenAICompatTransport._extract_cache_info(usage)
        reasoning = OpenAICompatTransport._extract_reasoning_tokens(usage)
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
            reasoning_tokens=reasoning)

    @staticmethod
    def _merge_partial_message(messages: List[Message], new_message: Message):
        messages[-1].reasoning_content += new_message.reasoning_content
        messages[-1].content += new_message.content
        messages[-1].prompt_tokens += new_message.prompt_tokens
        messages[-1].cached_tokens += new_message.cached_tokens
        messages[-1].cache_creation_input_tokens += \
            new_message.cache_creation_input_tokens
        messages[-1].completion_tokens += new_message.completion_tokens
        messages[-1].reasoning_tokens += new_message.reasoning_tokens
        if new_message.tool_calls:
            if messages[-1].tool_calls:
                messages[-1].tool_calls += new_message.tool_calls
            else:
                messages[-1].tool_calls = new_message.tool_calls

    def _call_llm_for_continue_gen(self,
                                   messages: List[Message],
                                   new_message: Message,
                                   tools: List[Tool] = None,
                                   **kwargs) -> Any:
        """Prepare and issue a continuation request.

        Unifies the DashScope ('partial') and DeepSeek ('prefix') paths via
        ``self._continue_flag``. Fixes two bugs from the legacy subclasses:
          * the stop list was clobbered by ``list.append`` returning ``None``;
          * the message formatter was called by a non-existent method name.
        """
        flag = self._continue_flag
        if messages[-1].to_dict().get(flag, False):
            self._merge_partial_message(messages, new_message)
        else:
            if messages[-1].content != new_message.content:
                messages.append(new_message)
            setattr(messages[-1], flag, True)
        messages[-1].api_calls += 1

        if self.continue_gen_mode == 'prefix' and self.continue_gen_stop:
            existing = list(kwargs.pop('stop', []) or [])
            kwargs['stop'] = existing + list(self.continue_gen_stop)

        return self._call_llm(messages, tools, **kwargs)

    def _continue_generate(self,
                           messages: List[Message],
                           completion,
                           tools: List[Tool] = None,
                           max_runs: Optional[int] = None,
                           **kwargs) -> Message:
        flag = self._continue_flag
        new_message = self._format_output_message(completion)
        if completion.choices[0].finish_reason in [
                'length', 'null'
        ] and (max_runs is None or max_runs != 0):
            logger.info(
                f'finish_reason: {completion.choices[0].finish_reason}, '
                f'continue generate.')
            completion = self._call_llm_for_continue_gen(
                messages, new_message, tools, **kwargs)
            return self._continue_generate(
                messages, completion, tools,
                max_runs - 1 if max_runs is not None else None, **kwargs)
        elif messages[-1].to_dict().get(flag, False):
            self._merge_partial_message(messages, new_message)
            setattr(messages[-1], flag, False)
            return messages.pop(-1)
        return new_message
