# Copyright (c) ModelScope Contributors. All rights reserved.
"""UI-independent question handling, separate from permission decisions."""
from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Protocol
from uuid import uuid4

from ms_agent.ui.interaction import (CUSTOM_OPTION_ID, Answer, AnswerStatus,
                                     Question, QuestionReply)

# Wait indefinitely by default; read environment overrides at construction.
QUESTION_ASK_TIMEOUT: float | None = None

UNAVAILABLE_NOTE = (
    'No interactive channel is available, so this question could not be put '
    'to anyone. Do not try again. Decide using the most reasonable default, '
    'and state plainly which assumption you made.')

SKIPPED_NOTE = ('The user chose not to answer. Proceed with the most '
                'reasonable default and say which assumption you made, or '
                'stop and explain what you still need.')

CANCELLED_NOTE = ('This question was withdrawn before it was answered (the '
                  'turn was stopped or the session closed). Nobody declined '
                  'anything — stop here rather than guessing.')


def _timeout_note(seconds: float) -> str:
    return (f'No answer within {seconds:.0f}s. This is a TIMEOUT, not a '
            'choice or a refusal. Do not ask it again; continue only with a '
            'safe stated assumption, or explain what information is missing.')


class QuestionEventEmitter(Protocol):
    """Protocol for pushing a raw question event to the host's transport."""

    def emit(self, event: Dict[str, Any]) -> None:
        ...


class AutoQuestionHandler:
    """Report unavailable interaction without fabricating answers."""

    supports_questions = False

    async def ask(self,
                  questions: List[Question],
                  call_id: str = '') -> QuestionReply:
        return QuestionReply(
            status=AnswerStatus.UNAVAILABLE, note=UNAVAILABLE_NOTE)


@dataclass
class _PendingQuestion:
    """One ask the user has not answered yet, and what it was about."""
    future: 'asyncio.Future[QuestionReply]'
    questions: List[Question]
    call_id: str


class WebQuestionHandler:
    """Await answers by request ID, independently of permission state."""

    supports_questions = True

    def __init__(
        self,
        event_emitter: QuestionEventEmitter,
        timeout: float | None = QUESTION_ASK_TIMEOUT,
    ) -> None:
        self._pending: Dict[str, _PendingQuestion] = {}
        self._event_emitter = event_emitter
        raw_timeout = os.environ.get('MSA_QUESTION_TIMEOUT')
        if timeout is None and raw_timeout:
            timeout = float(raw_timeout)
        if timeout is not None and (not math.isfinite(timeout)
                                    or timeout <= 0):
            raise ValueError(
                'Question timeout must be a positive finite number')
        self._timeout = timeout

    async def ask(self,
                  questions: List[Question],
                  call_id: str = '') -> QuestionReply:
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: 'asyncio.Future[QuestionReply]' = loop.create_future()
        questions = list(questions)
        # Register before emitting so immediate answers resolve correctly.
        # Emit inside try/finally so failures cannot leak a pending request.
        self._pending[request_id] = _PendingQuestion(
            future=future,
            questions=questions,
            call_id=str(call_id or ''),
        )
        try:
            self._event_emitter.emit({
                'type':
                'question_requested',
                'request_id':
                request_id,
                'call_id':
                str(call_id or ''),
                'questions': [q.to_dict() for q in questions],
            })
            if self._timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout=self._timeout)
        except asyncio.TimeoutError:
            return QuestionReply(
                status=AnswerStatus.TIMEOUT,
                note=_timeout_note(self._timeout or 0.0),
            )
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    # -- host-facing state ---------------------------------------------------

    def awaiting_request_ids(self) -> set:
        """Return pending request IDs for reconnects."""
        return {
            request_id
            for request_id, pending in self._pending.items()
            if not pending.future.done()
        }

    def is_awaiting(self, request_id: str) -> bool:
        """Check whether a request still awaits an answer."""
        pending = self._pending.get(request_id)
        return pending is not None and not pending.future.done()

    def pending_questions(self, request_id: str) -> List[Question]:
        """The questions of one open ask (for a host that re-renders them)."""
        pending = self._pending.get(request_id)
        return list(pending.questions) if pending else []

    # -- resolution ----------------------------------------------------------

    def resolve(self, request_id: str, answers: List[Answer]) -> bool:
        """Validate a complete answer set; reject invalid or repeated submissions."""
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            # Covers the ordinary races: a second click, a submission from
            # another tab, an answer arriving after the ask expired.
            return False
        validated = self._validate(pending.questions, answers)
        if validated is None:
            return False
        pending.future.set_result(
            QuestionReply(status=AnswerStatus.ANSWERED, answers=validated))
        return True

    def skip(self, request_id: str) -> bool:
        """The user declined to answer. Distinct from a cancel: they SAW it."""
        pending = self._pending.get(request_id)
        if pending is None or pending.future.done():
            return False
        pending.future.set_result(
            QuestionReply(status=AnswerStatus.SKIPPED, note=SKIPPED_NOTE))
        return True

    def cancel_pending(self, note: str = CANCELLED_NOTE) -> int:
        """Resolve pending requests before the host cancels execution."""
        resolved = 0
        for request_id, pending in list(self._pending.items()):
            if pending.future.done():
                continue
            pending.future.set_result(
                QuestionReply(status=AnswerStatus.CANCELLED, note=note))
            resolved += 1
            self._pending.pop(request_id, None)
        return resolved

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _validate(questions: List[Question],
                  answers: List[Answer]) -> List[Answer] | None:
        """Validate IDs and derive labels from the original options."""
        by_id = {q.id: q for q in questions}
        seen: set = set()
        out: List[Answer] = []
        for answer in answers:
            question = by_id.get(answer.question_id)
            if question is None or answer.question_id in seen:
                return None  # unknown or duplicated question
            seen.add(answer.question_id)
            option_ids = list(answer.option_ids)
            if len(option_ids) != len(set(option_ids)):
                return None
            custom = answer.custom_text.strip()
            if len(custom) > 2000:
                return None
            if CUSTOM_OPTION_ID in option_ids:
                if not question.allow_custom or not custom:
                    return None
            elif custom:
                return None  # free text without claiming the custom option
            if not option_ids:
                return None  # an answered question must carry a choice
            if not question.multi_select and len(option_ids) > 1:
                return None
            labels: List[str] = []
            for option_id in option_ids:
                if option_id == CUSTOM_OPTION_ID:
                    labels.append(custom)
                    continue
                option = question.option(option_id)
                if option is None:
                    return None
                labels.append(option.label)
            out.append(
                Answer(
                    question_id=answer.question_id,
                    option_ids=option_ids,
                    labels=labels,
                    custom_text=custom,
                ))
        if seen != set(by_id):
            return None
        # Preserve question order regardless of submission order.
        answers_by_id = {a.question_id: a for a in out}
        return [answers_by_id[q.id] for q in questions]


def make_question_handler(
    emit: Callable[[Dict[str, Any]], None],
    timeout: float | None = QUESTION_ASK_TIMEOUT,
) -> WebQuestionHandler:
    """Convenience for hosts that have a callable rather than an emitter."""

    class _Emitter:

        def emit(self, event: Dict[str, Any]) -> None:
            emit(event)

    return WebQuestionHandler(_Emitter(), timeout=timeout)
