# Copyright (c) Alibaba, Inc. and its affiliates.
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from typing_extensions import Literal, Required, TypedDict


class ToolCall(TypedDict, total=False):
    id: str = 'default_id'
    index: int = 0
    type: str = 'function'
    tool_name: Required[str]
    arguments: str = ''


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

    def to_dict(self):
        return asdict(self)
