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

    api_calls: int = 1

    # role=tool: extra payload for UIs / SSE only; omitted from LLM API via to_dict_clean().
    tool_detail: Optional[str] = None

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
            'searching_detail',
            'search_result',
            '_responses_output_items',
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
                extra={
                    k: v
                    for k, v in raw.items()
                    if k not in ['text', 'resources', 'result', 'tool_detail']
                })
        raise TypeError('tool_call_result must be str or dict')
