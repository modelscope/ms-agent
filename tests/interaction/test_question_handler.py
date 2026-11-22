# Copyright (c) ModelScope Contributors. All rights reserved.
"""用户提问能力及其回归测试。"""
import asyncio

from ms_agent.interaction import AutoQuestionHandler, WebQuestionHandler
from ms_agent.ui.interaction import (CUSTOM_OPTION_ID, Answer, AnswerStatus,
                                     Question, QuestionOption,
                                     answers_from_dicts)


class _Emitter:

    def __init__(self, on_emit=None):
        self.events = []
        self._on_emit = on_emit

    def emit(self, event):
        self.events.append(event)
        if self._on_emit is not None:
            self._on_emit(event)


def _question(multi=False, allow_custom=True):
    return Question(
        id='q0',
        header='Format',
        question='Which format?',
        options=[
            QuestionOption('q0_o0', 'CSV', 'comma separated'),
            QuestionOption('q0_o1', 'Excel', 'xlsx workbook'),
        ],
        multi_select=multi,
        allow_custom=allow_custom,
    )


def _ask(handler, questions, resolve):
    """Run one ask to completion, calling ``resolve(request_id)`` once it is
    registered."""

    async def main():
        task = asyncio.create_task(handler.ask(questions, call_id='call-1'))
        await asyncio.sleep(0)  # let ask() register + emit
        resolve()
        return await task

    return asyncio.run(main())


# ── registration ──────────────────────────────────────────────────────────


def test_request_is_registered_before_the_event_goes_out():
    """An answer that arrives during emit must still find its pending record"""
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    resolved: list = []

    def on_emit(event):
        # Inside emit: the record must already exist.
        resolved.append(
            handler.resolve(event['request_id'], [Answer('q0', ['q0_o1'])]))

    emitter._on_emit = on_emit
    reply = asyncio.run(handler.ask([_question()], call_id='c'))
    assert resolved == [True]
    assert reply.status is AnswerStatus.ANSWERED


def test_a_failed_emit_leaves_no_pending_record():
    """Otherwise the ask stays 'open' with no card anywhere able to close it."""

    class _Broken:

        def emit(self, event):
            raise RuntimeError('transport down')

    handler = WebQuestionHandler(_Broken())
    try:
        asyncio.run(handler.ask([_question()]))
    except RuntimeError:
        pass
    assert handler.awaiting_request_ids() == set()


def test_the_event_carries_the_questions_and_the_gating_call_id():
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    _ask(
        handler, [_question()], lambda: handler.resolve(
            emitter.events[0]['request_id'], [Answer('q0', ['q0_o0'])]))
    event = emitter.events[0]
    assert event['type'] == 'question_requested'
    assert event['call_id'] == 'call-1'
    assert event['questions'][0]['options'][0]['id'] == 'q0_o0'
    assert event['questions'][0]['header'] == 'Format'


# ── answering ─────────────────────────────────────────────────────────────


def test_labels_are_recomputed_from_the_ids_the_client_sent():
    """The ids are the answer; labels are derived"""
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    reply = _ask(
        handler, [_question()], lambda: handler.resolve(
            emitter.events[0]['request_id'],
            [Answer('q0', ['q0_o1'], labels=['Something else'])]))
    assert reply.answers[0].labels == ['Excel']


def test_multi_select_keeps_every_choice():
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    reply = _ask(
        handler, [_question(multi=True)], lambda: handler.resolve(
            emitter.events[0]['request_id'],
            [Answer('q0', ['q0_o0', 'q0_o1'])]))
    assert reply.answers[0].labels == ['CSV', 'Excel']


def test_free_text_answer_becomes_its_own_label():
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    reply = _ask(
        handler, [_question()], lambda: handler.resolve(
            emitter.events[0]['request_id'],
            [Answer('q0', [CUSTOM_OPTION_ID], custom_text='  Parquet  ')]))
    assert reply.answers[0].labels == ['Parquet']
    assert reply.answers[0].custom_text == 'Parquet'


# ── rejected submissions ──────────────────────────────────────────────────


def _rejects(answers, question=None):
    """Whether resolve() refuses these answers for one open ask."""
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    outcome: list = []

    async def main():
        task = asyncio.create_task(handler.ask([question or _question()]))
        await asyncio.sleep(0)
        rid = emitter.events[0]['request_id']
        outcome.append(handler.resolve(rid, answers))
        handler.skip(rid)  # unblock the turn so the test can finish
        await task

    asyncio.run(main())
    return outcome[0] is False


def test_an_option_that_does_not_exist_is_refused():
    assert _rejects([Answer('q0', ['made_up'])])


def test_a_single_select_question_refuses_several_options():
    assert _rejects([Answer('q0', ['q0_o0', 'q0_o1'])])


def test_an_unknown_question_id_is_refused():
    assert _rejects([Answer('q9', ['q0_o0'])])


def test_an_empty_choice_is_refused():
    assert _rejects([Answer('q0', [])])


def test_free_text_without_text_is_refused():
    assert _rejects([Answer('q0', [CUSTOM_OPTION_ID], custom_text='   ')])


def test_free_text_is_refused_where_the_question_forbids_it():
    assert _rejects([Answer('q0', [CUSTOM_OPTION_ID], custom_text='Parquet')],
                    question=_question(allow_custom=False))


def test_text_without_claiming_the_custom_option_is_refused():
    # Otherwise the model would be shown an option's label while the user's
    # typed text was silently dropped.
    assert _rejects([Answer('q0', ['q0_o0'], custom_text='actually Parquet')])


# ── one answer, once ──────────────────────────────────────────────────────


def test_a_second_submission_cannot_overwrite_an_accepted_answer():
    """Two tabs, one question. The first answer stands."""
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    second: list = []

    async def main():
        task = asyncio.create_task(handler.ask([_question()]))
        await asyncio.sleep(0)
        rid = emitter.events[0]['request_id']
        assert handler.resolve(rid, [Answer('q0', ['q0_o0'])]) is True
        second.append(handler.resolve(rid, [Answer('q0', ['q0_o1'])]))
        return await task

    reply = asyncio.run(main())
    assert second == [False]
    assert reply.answers[0].labels == ['CSV']


def test_an_unknown_request_is_refused():
    handler = WebQuestionHandler(_Emitter())
    assert handler.resolve('nope', [Answer('q0', ['q0_o0'])]) is False
    assert handler.skip('nope') is False
    assert handler.is_awaiting('nope') is False


def test_one_answer_never_settles_another_question():
    """The load-bearing difference from permissions"""
    assert not hasattr(WebQuestionHandler, 'resolve_matching')

    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)

    async def main():
        first = asyncio.create_task(handler.ask([_question()], call_id='a'))
        second = asyncio.create_task(handler.ask([_question()], call_id='b'))
        await asyncio.sleep(0)
        assert len(handler.awaiting_request_ids()) == 2
        handler.resolve(emitter.events[0]['request_id'],
                        [Answer('q0', ['q0_o0'])])
        await first
        # Answering the first left the second exactly where it was.
        assert len(handler.awaiting_request_ids()) == 1
        handler.skip(emitter.events[1]['request_id'])
        return await second

    assert asyncio.run(main()).status is AnswerStatus.SKIPPED


# ── the four non-answers ──────────────────────────────────────────────────


def test_skipping_says_the_user_declined():
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)
    reply = _ask(handler, [_question()],
                 lambda: handler.skip(emitter.events[0]['request_id']))
    assert reply.status is AnswerStatus.SKIPPED
    assert reply.answers == []
    assert 'default' in reply.note


def test_cancelling_is_not_a_refusal_and_answers_every_open_ask():
    emitter = _Emitter()
    handler = WebQuestionHandler(emitter)

    async def main():
        first = asyncio.create_task(handler.ask([_question()], call_id='a'))
        second = asyncio.create_task(handler.ask([_question()], call_id='b'))
        await asyncio.sleep(0)
        assert handler.cancel_pending() == 2
        return await first, await second

    a, b = asyncio.run(main())
    assert a.status is b.status is AnswerStatus.CANCELLED
    assert handler.awaiting_request_ids() == set()


def test_an_expiry_reports_itself_as_a_timeout_not_a_choice():
    """Naming it matters: a model told only "no answer" asks again and waits
    out the same silence a second time."""
    handler = WebQuestionHandler(_Emitter(), timeout=0.01)
    reply = asyncio.run(handler.ask([_question()]))
    assert reply.status is AnswerStatus.TIMEOUT
    assert 'TIMEOUT' in reply.note
    assert handler.awaiting_request_ids() == set()


def test_the_wait_is_unbounded_unless_ops_bound_it():
    """Nothing can answer "which format do you want" on the user's behalf, so
    the default cannot be to answer it for them."""
    from ms_agent.interaction.handler import QUESTION_ASK_TIMEOUT
    assert QUESTION_ASK_TIMEOUT is None
    assert WebQuestionHandler(_Emitter())._timeout is None


def test_no_channel_declares_itself_unusable():
    handler = AutoQuestionHandler()
    assert handler.supports_questions is False
    reply = asyncio.run(handler.ask([_question()]))
    assert reply.status is AnswerStatus.UNAVAILABLE
    assert 'Do not try again' in reply.note


# ── wire payloads ─────────────────────────────────────────────────────────


def test_answers_survive_the_round_trip_through_a_wire_payload():
    original = [
        Answer('q0', ['q0_o1'], labels=['Excel']),
        Answer('q1', [CUSTOM_OPTION_ID], custom_text='weekly'),
    ]
    restored = answers_from_dicts([a.to_dict() for a in original])
    assert [a.question_id for a in restored] == ['q0', 'q1']
    assert restored[1].custom_text == 'weekly'


def test_a_malformed_payload_yields_answers_the_handler_can_reject():
    # Lenient parsing, strict validation: resolve() is where a precise reason
    # is available, so parsing must not raise on junk.
    restored = answers_from_dicts([{}, 'nonsense', {'question_id': 'q0'}])
    assert len(restored) == 2
    assert restored[0].option_ids == []


def test_answers_must_cover_the_whole_request():
    first = _question()
    second = Question('q1', '图表', '选择图表', [
        QuestionOption('a', '柱状图'), QuestionOption('b', '折线图')])
    validate = WebQuestionHandler._validate
    assert validate([first, second], [Answer('q0', ['q0_o0'])]) is None
    reply = validate([first, second], [Answer('q1', ['b']), Answer('q0', ['q0_o1'])])
    assert [a.question_id for a in reply] == ['q0', 'q1']
    assert [a.labels for a in reply] == [['Excel'], ['折线图']]


def test_duplicate_options_and_long_custom_text_are_refused():
    assert _rejects([Answer('q0', ['q0_o0', 'q0_o0'])], _question(multi=True))
    assert _rejects([Answer('q0', [CUSTOM_OPTION_ID], custom_text='x' * 2001)])


def test_timeout_environment_is_read_when_constructing(monkeypatch):
    monkeypatch.setenv('MSA_QUESTION_TIMEOUT', '30')
    assert WebQuestionHandler(_Emitter())._timeout == 30
    for value in ['0', '-1', 'inf', 'nan', 'invalid']:
        monkeypatch.setenv('MSA_QUESTION_TIMEOUT', value)
        import pytest
        with pytest.raises(ValueError):
            WebQuestionHandler(_Emitter())
