"""用户提问能力及其回归测试。"""
import asyncio
from types import SimpleNamespace

import pytest
from app.backends.ms_agent.chat import _TurnMapper, _tool_step_meta
from app.backends.ms_agent.runtime import (QueueEventSink,
                                           _persisting_question_handler)
from ms_agent.ui.interaction import Answer, AnswerStatus, Question, QuestionOption

_QUESTIONS = [
    Question(
        id="q0",
        header="Format",
        question="Which format?",
        options=[
            QuestionOption("q0_o0", "CSV", "comma separated"),
            QuestionOption("q0_o1", "Excel", "xlsx workbook"),
        ],
    )
]


class _StubLog:
    """Just enough SessionLog for the question records."""

    def __init__(self):
        self.questions = []

    def record_question(self, event):
        self.questions.append(dict(event))

    def get_questions(self):
        return list(self.questions)


def _handler_with_log():
    sink = QueueEventSink()
    log = _StubLog()
    return _persisting_question_handler(sink, lambda: log), sink, log


def _ask_events(sink):
    return [e for e in sink._events if e.get("type") == "question_requested"]


def _resolved_events(sink):
    return [e for e in sink._events if e.get("type") == "question_resolved"]


# ── the card the ask becomes ───────────────────────────────────────────────


def test_the_ask_tool_renders_no_tool_card_of_its_own():
    """The question card carries the whole step. A generic "call tool" card
    beside it would be a second, emptier copy of the same thing — and it is the
    only one of the two that can be rendered from the tool call alone."""
    assert _tool_step_meta("ask_user---ask_user_question", {}) is None


def test_a_live_ask_becomes_one_answerable_card():
    mapper = _TurnMapper("sess-1")
    chunks = mapper.map({
        "type": "question_requested",
        "request_id": "req-1",
        "call_id": "call-1",
        "questions": [q.to_dict() for q in _QUESTIONS],
    })
    assert len(chunks) == 1
    meta = chunks[0].meta
    assert meta["kind"] == "question"
    assert meta["state"] == "pending"
    # request_id + session_id are what make the card interactive.
    assert meta["request_id"] == "req-1"
    assert meta["session_id"] == "sess-1"
    assert meta["questions"][0]["options"][0]["id"] == "q0_o0"


def test_an_outcome_frame_closes_the_card_and_carries_no_request_id():
    """No request_id is the signal: the outcome is final, so the card must
    render it instead of controls."""
    mapper = _TurnMapper("sess-1")
    chunks = mapper.map({
        "type": "question_resolved",
        "call_id": "call-1",
        "status": "answered",
        "answers": [{"question_id": "q0", "labels": ["Excel"]}],
    })
    meta = chunks[0].meta
    assert meta["kind"] == "question"
    assert meta["state"] == "answered"
    assert "request_id" not in meta
    assert meta["call_id"] == "call-1"


def test_a_question_seals_an_open_reasoning_block():
    """Otherwise the thinking timer keeps counting for as long as the user
    takes to answer, and the question renders inside the thought."""
    mapper = _TurnMapper("sess-1")
    mapper.map({"type": "reasoning_started"})
    mapper.map({"type": "reasoning_delta", "text": "hmm"})
    chunks = mapper.map({
        "type": "question_requested",
        "request_id": "req-1",
        "call_id": "call-1",
        "questions": [],
    })
    assert [c.type for c in chunks] == ["thought", "step"]
    assert chunks[0].meta.get("duration") is not None


# ── the answer route ──────────────────────────────────────────────────────


def _registry_with(handler):
    """A registry whose one session carries this handler."""
    from app.backends.ms_agent.runtime import RuntimeRegistry

    registry = RuntimeRegistry()
    registry._runtimes["sess-1"] = SimpleNamespace(question_handler=handler)
    return registry


def test_answering_resumes_the_suspended_turn():
    handler, sink, log = _handler_with_log()
    registry = _registry_with(handler)

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        request_id = _ask_events(sink)[0]["request_id"]
        assert registry.resolve_question(
            "sess-1", request_id, "answered",
            [{"question_id": "q0", "option_ids": ["q0_o1"], "custom_text": ""}],
        ) is True
        return await task

    reply = asyncio.run(main())
    assert reply.status is AnswerStatus.ANSWERED
    # Labels come back recomputed from the ids — the client never sent them.
    assert reply.answers[0].labels == ["Excel"]


def test_skipping_is_reported_as_such_not_as_an_answer():
    handler, sink, log = _handler_with_log()
    registry = _registry_with(handler)

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        request_id = _ask_events(sink)[0]["request_id"]
        assert registry.resolve_question("sess-1", request_id, "skipped",
                                         []) is True
        return await task

    reply = asyncio.run(main())
    assert reply.status is AnswerStatus.SKIPPED
    assert log.questions[0]["status"] == "skipped"


@pytest.mark.parametrize(
    "answers",
    [
        [{"question_id": "q0", "option_ids": ["nope"], "custom_text": ""}],
        [{"question_id": "q9", "option_ids": ["q0_o0"], "custom_text": ""}],
        [{"question_id": "q0", "option_ids": [], "custom_text": ""}],
        [],
    ],
)
def test_answers_that_do_not_fit_the_questions_are_refused(answers):
    """Refused, not coerced: the model must never be handed an answer nobody
    gave, and the ask stays open for a correct submission."""
    handler, sink, _ = _handler_with_log()
    registry = _registry_with(handler)
    outcome = []

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        request_id = _ask_events(sink)[0]["request_id"]
        outcome.append(
            registry.resolve_question("sess-1", request_id, "answered",
                                      answers))
        assert handler.is_awaiting(request_id) is True  # still open
        handler.skip(request_id)
        await task

    asyncio.run(main())
    assert outcome == [False]


def test_an_unknown_request_or_session_is_refused():
    handler, _, _ = _handler_with_log()
    registry = _registry_with(handler)
    assert registry.resolve_question("sess-1", "made-up", "answered", []) is False
    assert registry.resolve_question("other", "made-up", "answered", []) is False


def test_a_late_submission_cannot_reopen_a_closed_ask():
    """Two tabs, or a click after the turn was stopped. The route says no
    rather than resolving a Future that already fired."""
    handler, sink, _ = _handler_with_log()
    registry = _registry_with(handler)
    late = []

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        request_id = _ask_events(sink)[0]["request_id"]
        handler.skip(request_id)
        await task
        late.append(
            registry.resolve_question(
                "sess-1", request_id, "answered",
                [{"question_id": "q0", "option_ids": ["q0_o0"],
                  "custom_text": ""}]))

    asyncio.run(main())
    assert late == [False]


# ── announcements and persistence ─────────────────────────────────────────


def test_every_outcome_is_announced_so_other_viewers_can_close_the_card():
    """Unlike an approval, whose result card supersedes the ask, a question has
    no result card. Announcing only the ones no client caused would leave a
    second tab offering inputs for a question answered minutes ago."""
    handler, sink, _ = _handler_with_log()

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        handler.resolve(_ask_events(sink)[0]["request_id"],
                        [Answer("q0", ["q0_o1"])])
        await task

    asyncio.run(main())
    announced = _resolved_events(sink)
    assert len(announced) == 1
    assert announced[0]["status"] == "answered"
    assert announced[0]["call_id"] == "call-1"
    assert announced[0]["answers"][0]["labels"] == ["Excel"]


def test_the_outcome_is_persisted_with_the_questions_for_replay():
    handler, sink, log = _handler_with_log()

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        handler.resolve(_ask_events(sink)[0]["request_id"],
                        [Answer("q0", ["q0_o1"])])
        await task

    asyncio.run(main())
    record = log.questions[0]
    assert record["status"] == "answered"
    assert record["call_id"] == "call-1"
    # Both halves: without the questions a reload cannot say what was asked.
    assert record["questions"][0]["header"] == "Format"
    assert record["answers"][0]["labels"] == ["Excel"]


def test_a_cancelled_ask_is_announced_and_recorded_as_cancelled():
    """A stopped turn is not a refusal; the card and the log must both say so."""
    handler, sink, log = _handler_with_log()

    async def main():
        task = asyncio.create_task(handler.ask(_QUESTIONS, call_id="call-1"))
        await asyncio.sleep(0)
        assert handler.cancel_pending() == 1
        return await task

    reply = asyncio.run(main())
    assert reply.status is AnswerStatus.CANCELLED
    assert log.questions[0]["status"] == "cancelled"
    assert _resolved_events(sink)[0]["status"] == "cancelled"


def test_stopping_a_turn_mid_question_still_records_and_announces_it():
    """The real Stop order, not an idealized one"""
    handler, sink, log = _handler_with_log()

    async def main():
        # parallel_call_tool wraps each call in gather, i.e. its own Task.
        async def agent_round():
            return await asyncio.gather(
                handler.ask(_QUESTIONS, call_id="call-1"))

        run_task = asyncio.create_task(agent_round())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        # aclose(), verbatim in order: no await between these two lines.
        assert handler.cancel_pending() == 1  # the ask WAS suspended
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task

    asyncio.run(main())
    # Exactly one record and one announcement, whichever way the task woke.
    assert [r["status"] for r in log.questions] == ["cancelled"]
    assert log.questions[0]["questions"][0]["header"] == "Format"
    assert [e["status"] for e in _resolved_events(sink)] == ["cancelled"]
    assert handler.awaiting_request_ids() == set()


# ── replay ────────────────────────────────────────────────────────────────


def test_a_replayed_ask_shows_its_outcome_and_no_controls():
    mapper = _TurnMapper(
        "sess-1",
        resolved_questions=[{
            "call_id": "call-1",
            "status": "answered",
            "answers": [{"question_id": "q0", "labels": ["Excel"]}],
        }],
    )
    meta = mapper.map({
        "type": "question_requested",
        "request_id": "req-1",
        "call_id": "call-1",
        "questions": [q.to_dict() for q in _QUESTIONS],
    })[0].meta
    assert meta["state"] == "answered"
    # Emptied on purpose: a request_id is what the card treats as "still live".
    assert meta["request_id"] == ""
    assert meta["answers"][0]["labels"] == ["Excel"]


def test_an_ask_still_awaiting_replays_as_answerable():
    # Nothing pre-resolved => the pre-scan judged it live, so the card keeps
    # its request_id and the user can answer after a refresh.
    mapper = _TurnMapper("sess-1", resolved_questions=[])
    meta = mapper.map({
        "type": "question_requested",
        "request_id": "req-1",
        "call_id": "call-1",
        "questions": [q.to_dict() for q in _QUESTIONS],
    })[0].meta
    assert meta["state"] == "pending"
    assert meta["request_id"] == "req-1"


def test_history_replays_a_question_card_from_its_record():
    from app.backends.ms_agent.sessions import _question_step

    step = _question_step({
        "_type": "question",
        "call_id": "call-1",
        "status": "answered",
        "questions": [q.to_dict() for q in _QUESTIONS],
        "answers": [{"question_id": "q0", "labels": ["Excel"]}],
    })
    assert step is not None
    assert step.kind == "question"
    assert step.meta["state"] == "answered"
    # No request_id / session_id: a replayed card is read-only.
    assert "request_id" not in step.meta
    assert "session_id" not in step.meta


# ── the ask must not need authorizing ─────────────────────────────────────


def test_asking_the_user_does_not_itself_require_the_user_s_approval():
    """Two cards for one interaction, the first of them meaningless."""
    from app.backends.ms_agent.config import _PERMISSION_WHITELIST

    assert "ask_user---*" in _PERMISSION_WHITELIST


def test_replay_never_borrows_another_questions_answer():
    mapper = _TurnMapper('session', resolved_questions=[{
        'call_id': 'other', 'status': 'answered', 'answers': []}])
    meta = mapper.map({'type': 'question_requested', 'call_id': 'this',
                       'request_id': 'request', 'questions': []})[0].meta
    assert meta['state'] == 'pending'
    assert meta['request_id'] == 'request'


def test_answer_http_schema_limits_payload_size():
    from pydantic import ValidationError
    from app.api.chat import QuestionResolve
    with pytest.raises(ValidationError):
        QuestionResolve(session_id='s', request_id='r', answers=[{
            'question_id': 'q0', 'custom_text': 'x' * 2001}])


def test_question_marker_is_excluded_from_model_context(tmp_path):
    from ms_agent.session.session_log import SessionLog
    log = SessionLog(tmp_path, 'test')
    log.append({'role': 'user', 'content': 'original prompt'})
    log.record_question({'call_id': 'call', 'status': 'answered',
                         'questions': [], 'answers': []})
    assert [m.get('role') for m in log.get_all_messages()] == ['user']
    assert log.get_questions()[0]['status'] == 'answered'


@pytest.mark.parametrize('state', ['answered', 'skipped', 'cancelled', 'timeout'])
@pytest.mark.parametrize('marker_first', [True, False])
def test_question_replay_uses_call_position_not_marker_seq(state, marker_first):
    from app.backends.ms_agent.sessions import _reconstruct
    call = {'id': 'ask-call', 'tool_name': 'ask_user---ask_user_question',
            'arguments': {'questions': []}}
    assistant = {'role': 'assistant', 'content': '先确认格式',
                 'reasoning_content': '提问前的思考', 'tool_calls': [call]}
    marker = {'_type': 'question', 'call_id': 'ask-call', 'status': state,
              'questions': [q.to_dict() for q in _QUESTIONS],
              'answers': [{'question_id': 'q0', 'labels': ['Excel']}]}
    pair = [marker, assistant] if marker_first else [assistant, marker]
    rows = [{'role': 'user', 'content': '请提问'}, *pair,
            {'role': 'tool', 'tool_call_id': 'ask-call', 'content': '结果'},
            {'role': 'assistant', 'reasoning_content': '收到结果后的思考',
             'content': '已完成'}]
    rows = [{**row, 'seq': i} for i, row in enumerate(rows)]
    message = _reconstruct(rows)[1]
    kinds = [p.step.kind if p.kind == 'step' else p.kind for p in message.parts]
    assert kinds == ['thought', 'text', 'question', 'thought', 'text']
    step = message.parts[2].step
    assert step.meta['group'] == 1 and step.meta['state'] == state
    assert step.meta['call_id'] == 'ask-call'
    assert 'request_id' not in step.meta


def test_cancelled_question_stays_after_its_interrupted_thought():
    from app.backends.ms_agent.sessions import _reconstruct
    rows = [
        {'role': 'user', 'content': '请提问', 'seq': 0},
        {'_type': 'question', 'call_id': 'ask', 'status': 'cancelled', 'seq': 1,
         'questions': [], 'answers': []},
        {'role': 'assistant', 'interrupted_reasoning': '正在分析', 'content': '',
         'interrupted': True, 'seq': 2, 'tool_calls': [
             {'id': 'ask', 'tool_name': 'ask_user---ask_user_question', 'arguments': {}}]},
    ]
    kinds = [p.step.kind if p.kind == 'step' else p.kind
             for p in _reconstruct(rows)[1].parts]
    assert kinds == ['thought', 'question', 'interrupted']


def test_same_question_arguments_in_two_rounds_keep_separate_positions():
    from app.backends.ms_agent.sessions import _reconstruct
    marker = {'_type': 'question', 'questions': [], 'answers': []}
    rows = [{'role': 'user', 'content': '问两次'}]
    for i, status in enumerate(['answered', 'skipped']):
        rows += [dict(marker, call_id=f'call-{i}', status=status),
                 {'role': 'assistant', 'reasoning_content': f'思考{i}',
                  'tool_calls': [{'id': f'call-{i}',
                                  'tool_name': 'ask_user---ask_user_question',
                                  'arguments': {}}]}]
    rows += [{'role': 'assistant', 'content': '结束'}]
    parts = _reconstruct([{**r, 'seq': i} for i, r in enumerate(rows)])[1].parts
    assert [p.kind for p in parts] == ['thought', 'step', 'thought', 'step', 'text']
    assert [p.step.meta['state'] for p in parts if p.kind == 'step'] == ['answered', 'skipped']
    assert [p.step.meta['group'] for p in parts if p.kind == 'step'] == [1, 2]


def test_question_replay_keeps_sibling_tool_and_orphan_records():
    from app.backends.ms_agent.sessions import _reconstruct
    rows = [
        {'role': 'user', 'content': '并行调用'},
        {'_type': 'question', 'call_id': 'ask', 'status': 'answered'},
        {'role': 'assistant', 'reasoning_content': '思考', 'tool_calls': [
            {'id': 'read', 'tool_name': 'file_system---read_file', 'arguments': {'path': 'x'}},
            {'id': 'ask', 'tool_name': 'ask_user---ask_user_question', 'arguments': {}}]},
        {'_type': 'question', 'call_id': 'orphan', 'status': 'cancelled'},
        {'role': 'assistant', 'content': '完成'},
    ]
    parts = _reconstruct([{**r, 'seq': i} for i, r in enumerate(rows)])[1].parts
    assert [p.step.kind if p.kind == 'step' else p.kind for p in parts] == [
        'thought', 'file_read', 'question', 'question', 'text']
    assert parts[1].step.meta['group'] == parts[2].step.meta['group'] == 1
