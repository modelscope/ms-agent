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
from dataclasses import replace
from typing import Any, Dict, Generator, Iterator, List, Optional, Union

from ms_agent.llm import multimodal
from ms_agent.llm.thinking import apply_effort, create_with_thinking_fallback
from ms_agent.llm.transport.base import Transport
from ms_agent.llm.utils import Message, Tool, ToolCall
from ms_agent.llm.vision import create_with_vision_fallback
from ms_agent.llm.vision import delivery_reason as vision_delivery_reason
from ms_agent.utils import assert_package_exist, get_logger

logger = get_logger()


class AnthropicMessagesTransport(Transport):

    def __init__(
        self,
        model: str,
        api_key: Optional[str],
        base_url: str,
        generation_config: Optional[Dict] = None,
        vision: Optional['multimodal.VisionOptions'] = None,
        vision_supported: bool = True,
    ):
        assert_package_exist('anthropic', 'anthropic')
        import anthropic

        if not api_key:
            raise ValueError('Anthropic API key is required.')

        # See OpenAICompatTransport for why these are explicit params rather
        # than generation_config keys.
        self._vision = vision or multimodal.VisionOptions()
        self._vision_supported = bool(vision_supported)
        # What happened to each image on the most recently formatted request.
        self._last_deliveries: List[multimodal.ImageDelivery] = []

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

    @staticmethod
    def _blocks_from_structured(content: List[Any]) -> List[Dict[str, Any]]:
        """Translate an OpenAI-shaped content array to Anthropic blocks.

        Only reachable when a caller hands us structured content directly; our
        own attachment path builds Anthropic blocks natively. Unknown block
        kinds degrade to their text payload rather than being dropped silently.
        """
        out: List[Dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                out.append({'type': 'text', 'text': str(item)})
                continue
            kind = item.get('type')
            if kind == 'text':
                text = str(item.get('text') or '')
                if text:
                    out.append({'type': 'text', 'text': text})
            elif kind == 'image':  # already Anthropic-shaped
                out.append(item)
            elif kind in ('image_url', 'input_image'):
                url = item.get('image_url')
                url = url.get('url') if isinstance(url, dict) else url
                url = str(url or '')
                if url.startswith('data:') and ',' in url:
                    header, data = url.split(',', 1)
                    media_type = header[5:].split(';')[0] or 'image/png'
                    out.append({
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': media_type,
                            'data': data,
                        },
                    })
                elif url:
                    out.append({
                        'type': 'image',
                        'source': {
                            'type': 'url',
                            'url': url
                        },
                    })
            else:
                text = str(item.get('text') or '')
                if text:
                    out.append({'type': 'text', 'text': text})
        return out

    def _format_input_message(self,
                              messages: List[Message]) -> List[Dict[str, Any]]:
        formatted_messages = []
        # tool_use ids from the most recent assistant turn, awaiting their
        # results. Anthropic requires every tool_result to carry the matching
        # tool_use_id; mid-turn the tool Message can reach us before its id is
        # backfilled (it is present once persisted), so fall back to matching by
        # order — a null tool_use_id is rejected by the Messages API.
        pending_tool_ids: List[str] = []
        # One ordinal per PICTURE for the whole request; see
        # multimodal.image_index.
        numbering: Dict[str, int] = {}
        deliveries: List[multimodal.ImageDelivery] = []
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
            attachments = getattr(msg, 'attachments', None) or []
            if attachments and msg.role == 'user':
                # Image refs -> native image blocks (image-then-text, each
                # introduced by its own "Image N: <file>" label).
                built, planned = multimodal.anthropic_content(
                    msg.content if isinstance(msg.content, str) else '',
                    attachments,
                    self._vision,
                    vision_supported=self._images_allowed(),
                    reason=vision_delivery_reason(
                        getattr(self.client, 'base_url', ''), self.model),
                    numbering=numbering,
                    priors=[
                        str((a or {}).get('delivery') or '')
                        for a in attachments if isinstance(a, dict)
                    ])
                deliveries.extend(planned)
                if isinstance(built, list):
                    content.extend(built)
                elif built:
                    content.append({'type': 'text', 'text': str(built)})
            elif isinstance(msg.content, list):
                # Already-structured content (an image_url list handed in by an
                # SDK caller, or our own blocks on a replayed turn). Passing it
                # to _as_text would JSON-serialize the whole array into ONE text
                # block, silently destroying every image; convert instead.
                content.extend(self._blocks_from_structured(msg.content))
            elif msg.content:
                content.append({
                    'type': 'text',
                    'text': self._as_text(msg.content)
                })
            if msg.tool_calls:
                pending_tool_ids = []
                for tool_call in msg.tool_calls:
                    tid = tool_call['id']
                    pending_tool_ids.append(tid)
                    content.append({
                        'type':
                        'tool_use',
                        'id':
                        tid,
                        'name':
                        tool_call['tool_name'],
                        'input':
                        self._as_tool_input(tool_call.get('arguments'))
                    })
            if msg.role == 'tool':
                tool_use_id = msg.tool_call_id or (pending_tool_ids.pop(0)
                                                   if pending_tool_ids else '')
                # This protocol DOES allow image blocks inside tool_result, so a
                # tool's images stay attached to the call that produced them —
                # better than the hoist the OpenAI transports are forced into,
                # because the association survives regardless of message order.
                result_content: Any = self._as_text(msg.content)
                if multimodal.tool_media_withheld(attachments, self._vision,
                                                  self._images_allowed()):
                    # See the OpenAI transport: the tool's own text would
                    # otherwise be the last word on images this request drops.
                    result_content = '\n'.join(
                        filter(None,
                               [result_content, multimodal.TOOL_MEDIA_WITHHELD]))
                image_blocks = multimodal.anthropic_tool_result_blocks(
                    attachments,
                    self._vision,
                    vision_supported=self._images_allowed(),
                    numbering=numbering)
                if image_blocks:
                    text = result_content
                    result_content = [*image_blocks]
                    if text:
                        result_content.append({'type': 'text', 'text': text})
                result_block = {
                    'type': 'tool_result',
                    'tool_use_id': tool_use_id,
                    'content': result_content,
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
        self._last_deliveries = deliveries
        return formatted_messages

    def _images_allowed(self) -> bool:
        """Whether to encode pixels at all for this request.

        The per-model switch, and nothing else. There is deliberately no memory
        of past refusals to consult — see ``llm/vision.py`` for why.
        """
        return bool(self._vision_supported)

    def _mark_images_degraded(self, reason: str) -> None:
        """Correct this request's delivery record after recovery dropped images.

        The record is built while formatting, i.e. before the endpoint has had a
        chance to object, so left alone it would say "delivered" for exactly the
        requests the user most needs told about.
        """
        self._last_deliveries = [
            d if d.state != multimodal.DELIVERED else replace(
                d, state=multimodal.DEGRADED, reason=reason)
            for d in self._last_deliveries
        ]

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

        # Already lowered in `generate()` — it has to happen before the
        # signature filter there, and doing it twice is destructive (see the
        # note in transport/openai_compat.py).
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

        # Same per-model hard-400 hazard as the OpenAI-family transports: a model
        # that cannot accept images rejects the whole request rather than
        # ignoring the blocks. Retry once with the images folded into text and
        # remember the model. Symmetric with OpenAICompatTransport so behaviour
        # does not depend on which protocol a gateway happens to speak.
        sent_images = any(
            multimodal.has_image_blocks(m.get('content'))
            for m in formatted_messages if isinstance(m, dict))

        def _send(messages, **kw):
            call = dict(kw)
            call['messages'] = messages
            # `model` is a named parameter of create_with_vision_fallback (it
            # keys the per-model refusal memo), so it is consumed there rather
            # than forwarded — the API call has to name it again itself.
            call['model'] = self.model
            if stream:
                return self.client.messages.stream(**call)
            return self.client.messages.create(**call)

        # Thinking is the OTHER per-model hard-400, and this transport used to
        # be the one family without the repair: a Messages-API gateway fronting
        # a model that cannot think rejected the `thinking` block outright and
        # the error went straight to the user. Nested INSIDE the vision
        # fallback, exactly as in the OpenAI-family transports, so the two
        # retries compose instead of masking each other.
        def _create(messages, **kw):
            return create_with_thinking_fallback(
                lambda **kw2: _send(messages, **kw2),
                self.client,
                self.model,
                logger,
                **kw)

        # Everything except `model` and `messages`, which the wrapper takes as
        # named arguments; leaving either in `params` would collide with them.
        rest = {
            k: v
            for k, v in params.items() if k not in ('model', 'messages')
        }
        return create_with_vision_fallback(
            _create,
            base_url=getattr(self.client, 'base_url', ''),
            model=self.model,
            messages=params['messages'],
            sent_images=sent_images,
            max_edge=getattr(
                getattr(self, '_vision', None), 'max_edge', 0),
            on_degrade=self._mark_images_degraded,
            logger_=logger,
            **rest)

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

        # Before the signature filter: `reasoning_effort` is not a Messages API
        # parameter, so filtering first would drop the knob instead of lowering
        # it into this protocol's `thinking` block.
        args = apply_effort(args, base_url='', protocol='anthropic')

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
