# Copyright (c) ModelScope Contributors. All rights reserved.
"""Anthropic Messages API transport.

Faithful port of the ``Anthropic`` engine (``ms_agent/llm/anthropic_llm.py``)
into the data-driven provider layer, returning the legacy ``Message`` /
``Generator[Message]`` contract.

Improvement over the legacy engine: non-streaming responses now capture
``thinking`` blocks into ``reasoning_content`` (the legacy engine hardcoded it
to an empty string).
"""
from __future__ import annotations

import inspect
import json
from typing import (Any, Dict, Generator, Iterator, List, Optional, Union)

from ms_agent.llm.transport.base import Transport
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.utils import assert_package_exist


class AnthropicMessagesTransport(Transport):

    def __init__(
        self,
        model: str,
        api_key: Optional[str],
        base_url: str,
        generation_config: Optional[Dict] = None,
    ):
        assert_package_exist('anthropic', 'anthropic')
        import anthropic

        if not api_key:
            raise ValueError('Anthropic API key is required.')

        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.args: Dict = dict(generation_config or {})
        # The streaming response currently being iterated, exposed so interrupt()
        # can close it from another thread when the consumer abandons the stream.
        self._active_stream: Any = None

    def format_tools(self,
                     tools: Optional[List[Tool]]) -> Optional[List[Dict]]:
        if not tools:
            return None
        return [{
            'name': tool['tool_name'],
            'description': tool.get('description', ''),
            'input_schema': {
                'type': 'object',
                'properties': tool.get('parameters', {}).get('properties', {}),
                'required': tool.get('parameters', {}).get('required', []),
            }
        } for tool in tools]

    @staticmethod
    def _as_text(value: Any) -> str:
        """Anthropic text / tool_result content must be a string. A tool result
        (or, defensively, message content) can arrive mid-turn as a dict/list
        before it is stringified for the SessionLog; passing that through yields
        a `content: null` the Messages API rejects. Coerce: str as-is, None -> '',
        anything else -> compact JSON."""
        if isinstance(value, str):
            return value
        if value is None:
            return ''
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _as_tool_input(value: Any) -> Any:
        """Anthropic tool_use.input must be an object. Parse a JSON-string
        argument (OpenAI-style) back to a dict; leave dicts as-is."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return value if value is not None else {}

    def _format_input_message(
            self, messages: List[Message]) -> List[Dict[str, Any]]:
        formatted_messages = []
        # tool_use ids from the most recent assistant turn, awaiting their
        # results. Anthropic requires every tool_result to carry the matching
        # tool_use_id; mid-turn the tool Message can reach us before its id is
        # backfilled (it is present once persisted), so fall back to matching by
        # order — a null tool_use_id is rejected by the Messages API.
        pending_tool_ids: List[str] = []
        for msg in messages:
            content = []
            # Replay the assistant's thinking block (first, before text/tool_use)
            # with its signature. In thinking mode the provider rejects a tool
            # follow-up whose preceding assistant turn dropped its thinking block.
            if msg.role == 'assistant' and msg.reasoning_content:
                thinking_block: Dict[str, Any] = {
                    'type': 'thinking',
                    'thinking': msg.reasoning_content,
                }
                signature = getattr(msg, 'reasoning_signature', '') or ''
                if signature:
                    thinking_block['signature'] = signature
                content.append(thinking_block)
            if msg.content:
                content.append(
                    {'type': 'text', 'text': self._as_text(msg.content)})
            if msg.tool_calls:
                pending_tool_ids = []
                for tool_call in msg.tool_calls:
                    tid = tool_call['id']
                    pending_tool_ids.append(tid)
                    content.append({
                        'type': 'tool_use',
                        'id': tid,
                        'name': tool_call['tool_name'],
                        'input': self._as_tool_input(tool_call.get('arguments'))
                    })
            if msg.role == 'tool':
                tool_use_id = msg.tool_call_id or (
                    pending_tool_ids.pop(0) if pending_tool_ids else '')
                result_block = {
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': self._as_text(msg.content),
                }
                # Anthropic requires ALL tool_results for one assistant turn's
                # tool_use blocks in the SINGLE user message immediately after it.
                # Parallel tool calls arrive as consecutive tool Messages, so
                # merge them into that message rather than emitting one each
                # (which the API rejects: "tool_use ... without tool_result
                # immediately after").
                prev = formatted_messages[-1] if formatted_messages else None
                if (isinstance(prev, dict) and prev.get('role') == 'user'
                        and isinstance(prev.get('content'), list)
                        and prev['content']
                        and isinstance(prev['content'][0], dict)
                        and prev['content'][0].get('type') == 'tool_result'):
                    prev['content'].append(result_block)
                else:
                    formatted_messages.append({
                        'role': 'user',
                        'content': [result_block],
                    })
                continue
            formatted_messages.append({'role': msg.role, 'content': content})
        return formatted_messages

    def _call_llm(self,
                  messages: List[Message],
                  tools: Optional[List[Dict]] = None,
                  stream: bool = False,
                  **kwargs) -> Any:
        formatted_messages = self._format_input_message(messages)
        formatted_messages = [m for m in formatted_messages if m['content']]

        system = None
        if formatted_messages and formatted_messages[0]['role'] == 'system':
            system = formatted_messages[0]['content']
            formatted_messages = formatted_messages[1:]

        max_tokens = kwargs.pop('max_tokens', 16000)
        extra_body = kwargs.get('extra_body', {})
        enable_thinking = extra_body.get('enable_thinking', False)
        thinking_budget = extra_body.get('thinking_budget', max_tokens)

        params = {
            'model': self.model,
            'messages': formatted_messages,
            'max_tokens': max_tokens,
            'thinking': {
                'type': 'enabled' if enable_thinking else 'disabled',
                'budget_tokens': thinking_budget
            }
        }
        if system:
            params['system'] = system
        if tools:
            params['tools'] = tools
        params.update(kwargs)

        if stream:
            return self.client.messages.stream(**params)
        return self.client.messages.create(**params)

    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        **kwargs,
    ) -> Union[Message, Generator[Message, None, None]]:
        formatted_tools = self.format_tools(tools)
        args = self.args.copy()
        args.update(kwargs)
        stream = args.pop('stream', False)

        sig_params = inspect.signature(self.client.messages.create).parameters
        filtered_args = {k: v for k, v in args.items() if k in sig_params}

        completion = self._call_llm(messages, formatted_tools, stream,
                                    **filtered_args)

        if stream:
            return self._stream_format_output_message(completion)
        return self._format_output_message(completion)

    def _stream_format_output_message(self,
                                      stream_manager) -> Iterator[Message]:
        current_message = Message(
            role='assistant',
            content='',
            tool_calls=[],
            id='',
            completion_tokens=0,
            prompt_tokens=0,
            api_calls=1,
            partial=True,
        )
        tool_call_id_map = {}
        with stream_manager as stream:
            # Expose the live stream so interrupt() can close it from another
            # thread; the `with` still closes it on every normal/exception exit.
            self._active_stream = stream
            try:
                full_content = ''
                full_thinking = ''
                for event in stream:
                    event_type = getattr(event, 'type')
                    if event_type == 'message_start':
                        msg = event.message
                        current_message.id = msg.id
                        tool_call_id_map = {}
                        yield current_message
                    elif event_type == 'content_block_delta':
                        if event.delta.type == 'thinking_delta':
                            full_thinking += event.delta.thinking
                            current_message.reasoning_content = full_thinking
                        elif event.delta.type == 'text_delta':
                            full_content += event.delta.text
                            current_message.content = full_content
                        yield current_message
                    elif event_type == 'message_stop':
                        final_msg = getattr(event, 'message')
                        full_content = ''
                        for idx, block in enumerate(event.message.content):
                            if block is None:
                                continue
                            if block.type == 'text':
                                full_content += block.text
                            elif block.type == 'thinking':
                                # Capture the final thinking text + its opaque
                                # signature so a multi-turn tool conversation can
                                # replay the block verbatim (the provider rejects
                                # a thinking turn that isn't passed back).
                                current_message.reasoning_content = getattr(
                                    block, 'thinking',
                                    '') or current_message.reasoning_content
                                current_message.reasoning_signature = getattr(
                                    block, 'signature', '') or ''
                            elif block.type == 'tool_use':
                                tool_call_id = tool_call_id_map.get(
                                    idx, block.id)
                                current_message.tool_calls.append(
                                    ToolCall(
                                        id=tool_call_id,
                                        index=len(current_message.tool_calls),
                                        type='function',
                                        tool_name=block.name,
                                        arguments=block.input,
                                    ))
                        current_message.content = full_content
                        current_message.partial = False
                        current_message.completion_tokens = getattr(
                            final_msg.usage, 'output_tokens',
                            current_message.completion_tokens)
                        current_message.prompt_tokens = getattr(
                            final_msg.usage, 'input_tokens',
                            current_message.prompt_tokens)
                        yield current_message
            finally:
                if self._active_stream is stream:
                    self._active_stream = None

    @staticmethod
    def _close_stream(stream: Any) -> None:
        """Close a streaming response, swallowing any teardown error (it may be
        already closed/exhausted, or closed concurrently by interrupt)."""
        if stream is None:
            return
        try:
            close = getattr(stream, 'close', None)
            if callable(close):
                close()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass

    def interrupt(self) -> None:
        """Close the in-flight streaming response so the server stops generating.

        Called when the consumer abandons the stream mid-generation. Safe to call
        from a different thread than the one iterating the stream: closing the
        underlying HTTP response unblocks that read. A no-op when nothing streams.
        """
        self._close_stream(self._active_stream)

    @staticmethod
    def _format_output_message(completion) -> Message:
        content = ''
        reasoning_content = ''
        tool_calls = []
        for block in completion.content:
            if block.type == 'text':
                content += block.text
            elif block.type == 'thinking':
                # Legacy engine dropped this; capture it here.
                reasoning_content += getattr(block, 'thinking', '')
            elif block.type == 'tool_use':
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        index=len(tool_calls),
                        type='function',
                        arguments=block.input,
                        tool_name=block.name,
                    ))
        return Message(
            role='assistant',
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls if tool_calls else None,
            id=completion.id,
            prompt_tokens=completion.usage.input_tokens,
            completion_tokens=completion.usage.output_tokens,
        )
