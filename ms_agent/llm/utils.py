# Copyright (c) ModelScope Contributors. All rights reserved.
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Union
from typing_extensions import Literal, Required, TypedDict


class ToolCall(TypedDict, total=False):
    id: str = 'default_id'
    index: int = 0
    type: str = 'function'
    tool_name: str = ''
    arguments: str = '{}'


class Tool(TypedDict, total=False):
    server_name: str = None

    tool_name: Required[str]

    description: Required[str]

    parameters: Dict[str, Any] = dict()


def collect_response(response):
    """Normalize an LLM ``generate()`` return value to a single complete
    :class:`Message`.

    ``LLM.generate()`` returns either a ``Message`` (non-streaming) or a
    ``Generator[Message, None, None]`` (streaming).  In the streaming case
    the generator yields progressively accumulated ``Message`` objects and
    the last one contains the full response.  This helper transparently
    consumes the generator so callers that only need the final result can
    work identically regardless of the ``stream`` config.

    Usage::

        response = collect_response(llm.generate(messages))
        text = response.content
    """
    if isinstance(response, Message):
        return response
    msg = None
    for msg in response:
        pass
    return msg


@dataclass
class Message:
    role: Literal['system', 'user', 'assistant', 'tool']

    content: Union[str, List[Dict[str, str]]] = ''

    tool_calls: List[ToolCall] = field(default_factory=list)

    tool_call_id: Optional[str] = None

    # Also defined in OpenAI message
    name: Optional[str] = None

    # needed for output
    reasoning_content: str = ''

    # Anthropic extended-thinking blocks carry an opaque signature that must be
    # sent back verbatim in a multi-turn tool conversation (the provider rejects
    # a thinking block whose signature is missing/altered). Captured from the
    # streaming response and replayed by AnthropicMessagesTransport.
    reasoning_signature: str = ''

    # Opaque output items from the Responses API that must be passed back
    # in multi-turn tool-calling conversations (e.g. reasoning items).
    _responses_output_items: List[Dict[str, Any]] = field(default_factory=list)

    # request id
    id: str = ''

    # continue generation mode
    partial: bool = False
    prefix: bool = False

    # UI resources from mcp result
    resources: List[Dict[str, str]] = field(default_factory=list)

    # usage
    completion_tokens: int = 0
    prompt_tokens: int = 0

    # tokens that hit existing cache (billed at reduced rate like 0.1x)
    cached_tokens: int = 0
    # tokens used to create new cache (explicit cache only, billed at higher rate like 1.25x)
    cache_creation_input_tokens: int = 0
    # reasoning/thinking tokens (subset of completion_tokens for thinking models)
    reasoning_tokens: int = 0

    api_calls: int = 1

    # role=tool: extra payload for UIs / SSE only; omitted from LLM API via to_dict_clean().
    tool_detail: Optional[str] = None

    # Hook attachments for UI / LLM condensation; omitted from to_dict_clean().
    hook_attachments: List[Any] = field(default_factory=list)

    # role=tool: the tool call failed (the error text is in ``content``).
    # UI/persistence only — omitted from to_dict_clean() so it is never sent to
    # the model provider (the model still sees the failure via ``content``).
    is_error: bool = False

    # Non-text parts riding alongside ``content`` — today only images. Ordered:
    # entry i is "Image i+1" to the model, and the UI must show its chips in the
    # same order or "the second image" points at the wrong one.
    #
    # Each entry is a REFERENCE, not bytes:
    #     {'type': 'image', 'path': 'user_files/a.png',
    #      'media_type': 'image/png', 'label': 'Image 1: a.png'}
    #
    # Deliberately NOT folded into ``content``: this framework has ~40 call
    # sites that read a user message's ``content`` expecting a string (memory
    # extraction, full-text indexing, session auto-naming, summary compaction,
    # snapshot labels, hook prompt extraction). None of them wants to know how
    # many images there are, and none of them would crash loudly if handed a
    # block list — they would silently store a Python repr or skip the turn.
    # Keeping ``content`` a str keeps all of them correct for free; the
    # transports expand these refs into provider-native blocks at the wire.
    #
    # Storing a reference rather than base64 is what lets the same log be
    # re-encoded per provider (Anthropic 1568px/2576px tiers, DashScope not
    # accepting GIF) and lets a session survive a model switch: swap to a
    # text-only model and the refs degrade to text placeholders; swap back and
    # the images are visible again.
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def to_dict_clean(self):
        raw_dict = asdict(self)
        if raw_dict.get('tool_calls'):
            for idx, tool_call in enumerate(raw_dict['tool_calls']):
                try:
                    if tool_call['arguments']:
                        json.loads(tool_call['arguments'])
                except Exception:
                    tool_call['arguments'] = '{}'
                raw_dict['tool_calls'][idx] = {
                    'id': tool_call['id'],
                    'type': tool_call['type'],
                    'function': {
                        'name': tool_call['tool_name'],
                        'arguments': tool_call['arguments'],
                    }
                }
        required = ['content', 'role']
        # Never send UI-only fields to model providers.
        rm = [
            'completion_tokens',
            'prompt_tokens',
            'api_calls',
            'tool_detail',
            'hook_attachments',
            'is_error',
            'searching_detail',
            'search_result',
            '_responses_output_items',
            # Image refs are the transports' input, never wire output: each
            # provider adapter reads ``message.attachments`` BEFORE calling this
            # and folds them into provider-native content blocks. Leaving them
            # in would ship a bare {'type':'image','path':...} to the endpoint.
            # This entry is load-bearing: to_dict_clean() keeps every truthy
            # field not listed here, so omitting it leaks the refs.
            'attachments',
        ]
        return {
            key: value
            for key, value in raw_dict.items()
            if (value or key in required) and key not in rm
        }


@dataclass
class ToolResult:
    """Tool execution outcome.

    ``text`` is sent to the model as the tool message ``content``.
    ``tool_detail`` is optional verbose output for frontends only (SSE, logs).
    """

    text: str
    resources: List[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    tool_detail: Optional[str] = None
    hook_attachments: List[Any] = field(default_factory=list)
    is_error: bool = False
    #: Non-text parts the tool produced (images), same reference shape as
    #: ``Message.attachments``. ``text`` still carries a short human/model
    #: readable status; these carry the pixels. Splitting them is the point: a
    #: tool that put base64 into ``text`` was writing into the one channel a
    #: model cannot decode.
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_raw(raw):
        if isinstance(raw, str):
            return ToolResult(text=raw)
        if isinstance(raw, dict):
            model_text = raw.get('result')
            if model_text is None:
                model_text = raw.get('text', '')
            td = raw.get('tool_detail')
            return ToolResult(
                text=str(model_text),
                resources=raw.get('resources', []),
                tool_detail=None if td is None else str(td),
                hook_attachments=raw.get('hook_attachments', []),
                is_error=bool(raw.get('is_error', False)),
                attachments=raw.get('attachments', []) or [],
                extra={
                    k: v
                    for k, v in raw.items() if k not in [
                        'text',
                        'resources',
                        'result',
                        'tool_detail',
                        'hook_attachments',
                        'is_error',
                        'attachments',
                    ]
                })
        raise TypeError('tool_call_result must be str or dict')
