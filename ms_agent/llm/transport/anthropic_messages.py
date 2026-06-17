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

    def _format_input_message(
            self, messages: List[Message]) -> List[Dict[str, Any]]:
        formatted_messages = []
        for msg in messages:
            content = []
            if msg.content:
                content.append({'type': 'text', 'text': msg.content})
            if msg.tool_calls:
                for tool_call in msg.tool_calls:
                    content.append({
                        'type': 'tool_use',
                        'id': tool_call['id'],
                        'name': tool_call['tool_name'],
                        'input': tool_call.get('arguments', {})
                    })
            if msg.role == 'tool':
                formatted_messages.append({
                    'role':
                    'user',
                    'content': [{
                        'type': 'tool_result',
                        'tool_use_id': msg.tool_call_id,
                        'content': msg.content
                    }]
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
                        elif block.type == 'tool_use':
                            tool_call_id = tool_call_id_map.get(idx, block.id)
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
