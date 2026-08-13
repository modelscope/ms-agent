"""_seal_errored_turn: a failed turn must survive a reload — exactly once.

The DRIVER_ERROR branch calls this before the done frame. Its contract:

- a PRE-AGENT failure (credential resolution, agent construction) persisted
  nothing — the user's prompt must be written, else refresh blanks the view;
- once an agent exists, the SDK owns turn persistence (it consumed the prompt
  and its exception handler seals the round) — the seal here must never
  re-append the prompt, or every in-round failure doubles the whole turn;
- the sealing row is flagged ``errored``, never ``interrupted`` (UIs render
  the latter as a user-initiated Stop badge);
- the error record is written at most once per turn.
"""
from types import SimpleNamespace

import app.backends.ms_agent.chat as chat
from app.backends.ms_agent.chat import _INTERRUPTED_PLACEHOLDER, _seal_errored_turn


class _StubLog:
    """Just enough SessionLog: append/get_all_messages/get_errors/record_error."""

    def __init__(self, rows=None, errors=None):
        self.rows = list(rows or [])
        self.errors = list(errors or [])

    def _next_seq(self):
        seqs = [r.get("seq", -1) for r in self.rows + self.errors]
        return (max(seqs) + 1) if seqs else 0

    def get_all_messages(self):
        return list(self.rows)

    def append(self, record):
        record = dict(record)
        record.setdefault("seq", self._next_seq())
        self.rows.append(record)
        return record["seq"]

    def get_errors(self):
        return list(self.errors)

    def record_error(self, event):
        event = dict(event)
        event.setdefault("seq", self._next_seq())
        self.errors.append(event)


def _rt_with_agent(log):
    return SimpleNamespace(agent=SimpleNamespace(session_log=log))


def _rt_without_agent(monkeypatch, log):
    """Construction failed before the runtime exposed an agent; the seal must
    reach the log the way replay does (find_session -> get_session_log)."""
    sm = SimpleNamespace(get_session_log=lambda _session: log)
    monkeypatch.setattr(chat, "find_session",
                        lambda _sid: (object(), object(), sm))
    return SimpleNamespace(agent=None)


def test_pre_agent_failure_writes_prompt_seal_and_error(monkeypatch):
    log = _StubLog()  # only the metadata header existed on disk
    rt = _rt_without_agent(monkeypatch, log)

    _seal_errored_turn(rt, "sid", "你好", message="ValueError: no key")

    assert [r["role"] for r in log.rows] == ["user", "assistant"]
    assert log.rows[0]["content"] == "你好"
    seal = log.rows[1]
    assert seal["errored"] is True
    assert seal["content_placeholder"] is True
    assert seal["content"] == _INTERRUPTED_PLACEHOLDER
    assert "interrupted" not in seal  # errored must not render as a Stop badge
    assert [e["message"] for e in log.errors] == ["ValueError: no key"]
    assert log.errors[0]["recoverable"] is False


def test_in_round_failure_already_sealed_by_sdk_adds_nothing():
    """The regression that doubled every failed turn: the SDK's own seal closes
    the tail, and a closed tail must NOT be read as "turn never persisted"."""
    log = _StubLog(
        rows=[
            {"role": "user", "content": "测试", "seq": 1},
            {"role": "assistant", "content": _INTERRUPTED_PLACEHOLDER,
             "content_placeholder": True, "errored": True, "seq": 2},
        ],
        errors=[{"message": "AuthenticationError: 401", "round": 0, "seq": 3}],
    )

    _seal_errored_turn(
        _rt_with_agent(log), "sid", "测试",
        message="AuthenticationError: 401")

    assert [r["role"] for r in log.rows] == ["user", "assistant"]  # unchanged
    assert len(log.errors) == 1  # SDK's record stands; no duplicate


def test_in_round_failure_with_open_tail_seals_without_duplicating_prompt():
    # The SDK persisted this turn's user row and a dangling tool tail, but its
    # own seal could not run (e.g. the failure predated pre_step_len capture).
    log = _StubLog(rows=[
        {"role": "user", "content": "搜新闻", "seq": 0},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}],
         "seq": 1},
        {"role": "tool", "content": "results", "tool_call_id": "c1", "seq": 2},
    ])

    _seal_errored_turn(
        _rt_with_agent(log), "sid", "搜新闻", message="APIError: <400> x")

    users = [r for r in log.rows if r["role"] == "user"]
    assert len(users) == 1  # the SDK's copy is the only copy
    assert log.rows[-1]["errored"] is True  # tail is sealed
    assert len(log.errors) == 1  # reason recorded (SDK never got to it)


def test_error_already_recorded_for_this_turn_is_not_duplicated():
    log = _StubLog(
        rows=[{"role": "user", "content": "hi", "seq": 0}],
        errors=[{"message": "APIError: boom", "seq": 1}],
    )

    _seal_errored_turn(
        _rt_with_agent(log), "sid", "hi", message="APIError: boom")

    assert len(log.errors) == 1
    assert log.rows[-1]["errored"] is True  # the seal itself still happens


def test_consecutive_pre_agent_failures_each_get_their_own_record(monkeypatch):
    log = _StubLog()
    rt = _rt_without_agent(monkeypatch, log)
    _seal_errored_turn(rt, "sid", "第一次", message="E: 1")
    _seal_errored_turn(rt, "sid", "第二次", message="E: 2")
    _seal_errored_turn(rt, "sid", "第三次", message="E: 3")

    assert [r["role"] for r in log.rows] == [
        "user", "assistant", "user", "assistant", "user", "assistant"
    ]
    assert [e["message"] for e in log.errors] == ["E: 1", "E: 2", "E: 3"]
