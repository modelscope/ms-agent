# Copyright (c) Alibaba, Inc. and its affiliates.
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import json
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

    content: str = ''

    tool_calls: List[ToolCall] = field(default_factory=list)

    tool_call_id: Optional[str] = None

    name: Optional[str] = None

    # needed for output
    reasoning_content: str = ''

    # request id
    id: str = ''

    # continue generation mode
    partial: bool = False
    prefix: bool = False

    # usage
    completion_tokens: int = 0
    prompt_tokens: int = 0
    api_calls: int = 1

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
                    'index': tool_call['index'],
                    'type': tool_call['type'],
                    'function': {
                        'name': tool_call['tool_name'],
                        'arguments': tool_call['arguments'],
                    }
                }
        required = ['content', 'role']
        rm = ['completion_tokens', 'prompt_tokens', 'api_calls']
        return {
            key: value
            for key, value in raw_dict.items()
            if (value or key in required) and key not in rm
        }
