# Copyright (c) ModelScope Contributors. All rights reserved.
"""用户提问能力及其回归测试。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Protocol, runtime_checkable

#: Option id reserved for the free-text answer a question offers.
#:
#: The client appends that option itself, which is why the id is a constant
#: rather than something the model authors: asked to provide one, a model
#: writes "Other" / "以上都不是" / "custom" interchangeably, and a renderer
#: cannot reliably turn any of those into a text input.
CUSTOM_OPTION_ID = '__custom__'

#: Product bounds on one ask. Not protocol limits — they exist to keep the
#: user's burden survivable (four questions fill a card; a fifth is a form)
#: and to force the model to converge instead of externalizing its own
#: deliberation. Mirrored in the tool's JSON schema.
MAX_QUESTIONS = 4
MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_HEADER_CHARS = 12


@dataclass(frozen=True)
class QuestionOption:
    """选项编号用于关联答案，显示文案可独立调整。"""
    id: str
    label: str
    description: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'label': self.label,
            'description': self.description,
        }


@dataclass(frozen=True)
class Question:
    """One question, with the choices the model considers exhaustive."""
    id: str
    header: str  # very short chip for the UI, <= MAX_HEADER_CHARS
    question: str
    options: List[QuestionOption] = field(default_factory=list)
    multi_select: bool = False
    #: Whether the client should offer a free-text answer alongside the
    #: options. On by default: the model's list is its best guess at the
    #: choices, not a proof that no other answer exists.
    allow_custom: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'header': self.header,
            'question': self.question,
            'options': [o.to_dict() for o in self.options],
            'multi_select': self.multi_select,
            'allow_custom': self.allow_custom,
        }

    def option(self, option_id: str) -> 'QuestionOption | None':
        for option in self.options:
            if option.id == option_id:
                return option
        return None


class AnswerStatus(str, Enum):
    """区分回答、跳过、取消、超时和无交互通道。"""
    ANSWERED = 'answered'
    SKIPPED = 'skipped'  # a person declined to answer
    CANCELLED = 'cancelled'  # turn stopped / session closed under the ask
    TIMEOUT = 'timeout'  # nobody ever saw it
    UNAVAILABLE = 'unavailable'  # no interactive channel at all


@dataclass(frozen=True)
class Answer:
    """单题答案；labels 由服务端根据 option_ids 计算。"""
    question_id: str
    option_ids: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    custom_text: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'question_id': self.question_id,
            'option_ids': list(self.option_ids),
            'labels': list(self.labels),
            'custom_text': self.custom_text,
        }


@dataclass(frozen=True)
class QuestionReply:
    """The terminal outcome of one ask."""
    status: AnswerStatus
    answers: List[Answer] = field(default_factory=list)
    #: Said to the MODEL when ``status`` is not ANSWERED, in words that name
    #: which of the four non-answers happened and what to do about it.
    note: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {
            'status': self.status.value,
            'answers': [a.to_dict() for a in self.answers],
            'note': self.note,
        }


def answers_from_dicts(payload: Any) -> List[Answer]:
    """解析传输数据，完整性由回答服务校验。"""
    out: List[Answer] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        out.append(
            Answer(
                question_id=str(item.get('question_id') or ''),
                option_ids=[str(i) for i in (item.get('option_ids') or [])],
                labels=[str(i) for i in (item.get('labels') or [])],
                custom_text=str(item.get('custom_text') or ''),
            ))
    return out


@runtime_checkable
class QuestionHandler(Protocol):
    """宿主注入的回答入口；无交互通道时不注册提问工具。"""

    supports_questions: bool

    async def ask(self,
                  questions: List[Question],
                  call_id: str = '') -> QuestionReply:
        ...
