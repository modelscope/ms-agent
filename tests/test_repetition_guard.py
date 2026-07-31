"""Tests for RepetitionGuardCallback."""

from __future__ import annotations

import json

import pytest
from omegaconf import DictConfig

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.repetition_guard import (
    RepetitionGuardCallback,
    _args_hash,
    _detect_repetition,
    _extract_recent_tool_calls,
    _summarize_call,
)
from ms_agent.llm.utils import Message


def _make_config(**overrides) -> DictConfig:
    guard = {"threshold": 3, "lookback_rounds": 8, "max_warnings": 2}
    guard.update(overrides)
    return DictConfig({"repetition_guard": guard})


def _tool_call(tool_name: str, arguments: dict | str, call_id: str = "c1") -> dict:
    args = json.dumps(arguments) if isinstance(arguments, dict) else arguments
    return {
        "id": call_id,
        "type": "function",
        "tool_name": tool_name,
        "arguments": args,
    }


def _assistant_with_tools(*tool_calls) -> Message:
    return Message(role="assistant", content="Let me do a tool calling.", tool_calls=list(tool_calls))


def _tool_result(call_id: str, content: str = "ok") -> Message:
    return Message(role="tool", content=content, tool_call_id=call_id)


class TestArgsHash:
    def test_identical_dicts(self):
        a = _args_hash('{"command": "ls", "timeout": 30}')
        b = _args_hash('{"timeout": 30, "command": "ls"}')
        assert a == b

    def test_different_args(self):
        a = _args_hash('{"command": "ls"}')
        b = _args_hash('{"command": "pwd"}')
        assert a != b

    def test_invalid_json(self):
        h = _args_hash("not json")
        assert isinstance(h, str) and len(h) == 12


class TestExtractRecentToolCalls:
    def test_empty_messages(self):
        assert _extract_recent_tool_calls([], 8) == []

    def test_collects_from_assistant_messages(self):
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
            _assistant_with_tools(_tool_call("shell", {"command": "ls"})),
            _tool_result("c1", "file1 file2"),
            _assistant_with_tools(_tool_call("shell", {"command": "pwd"})),
            _tool_result("c1", "/app"),
        ]
        calls = _extract_recent_tool_calls(msgs, 8)
        assert len(calls) == 2
        assert calls[0][0] == "shell"
        assert calls[1][0] == "shell"

    def test_respects_lookback(self):
        msgs = [Message(role="system", content="sys")]
        for i in range(10):
            msgs.append(_assistant_with_tools(_tool_call("shell", {"command": f"cmd{i}"}, f"c{i}")))
            msgs.append(_tool_result(f"c{i}"))

        calls = _extract_recent_tool_calls(msgs, 3)
        assert len(calls) == 3


class TestDetectRepetition:
    def test_no_repetition(self):
        calls = [
            ("shell", "hash1", "shell(ls)"),
            ("shell", "hash2", "shell(pwd)"),
            ("shell", "hash3", "shell(cat)"),
        ]
        assert _detect_repetition(calls, 3) is None

    def test_detects_at_threshold(self):
        calls = [
            ("shell", "abc123", "shell(ls)"),
            ("shell", "abc123", "shell(ls)"),
            ("shell", "abc123", "shell(ls)"),
        ]
        rep = _detect_repetition(calls, 3)
        assert rep is not None
        assert rep.count == 3
        assert rep.tool_name == "shell"

    def test_below_threshold(self):
        calls = [
            ("shell", "abc123", "shell(ls)"),
            ("shell", "abc123", "shell(ls)"),
        ]
        assert _detect_repetition(calls, 3) is None

    def test_empty_calls(self):
        assert _detect_repetition([], 3) is None


class TestSummarizeCall:
    def test_command_arg(self):
        s = _summarize_call("shell", '{"command": "ls -la"}')
        assert "shell" in s
        assert "ls -la" in s

    def test_truncates_long_command(self):
        long_cmd = "x" * 200
        s = _summarize_call("shell", json.dumps({"command": long_cmd}))
        assert len(s) < 200
        assert "..." in s


class TestRepetitionGuardCallback:
    @pytest.mark.asyncio
    async def test_no_trigger_on_varied_calls(self):
        cb = RepetitionGuardCallback(_make_config())
        runtime = Runtime()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
        ]
        for i in range(5):
            msgs.append(_assistant_with_tools(_tool_call("shell", {"command": f"cmd{i}"}, f"c{i}")))
            msgs.append(_tool_result(f"c{i}"))

        await cb.after_tool_call(runtime, msgs)
        user_msgs = [m for m in msgs if m.role == "user"]
        assert len(user_msgs) == 1

    @pytest.mark.asyncio
    async def test_triggers_on_repeated_calls(self):
        cb = RepetitionGuardCallback(_make_config())
        runtime = Runtime()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
        ]
        for i in range(3):
            msgs.append(
                _assistant_with_tools(
                    _tool_call("shell", {"command": "make build"}, f"c{i}")
                )
            )
            msgs.append(_tool_result(f"c{i}", "error: build failed"))

        await cb.after_tool_call(runtime, msgs)
        user_msgs = [m for m in msgs if m.role == "user"]
        assert len(user_msgs) == 2
        injected = user_msgs[-1].content
        assert "repeating the same approach" in injected
        assert "make build" in injected
        assert runtime.should_stop is False

    @pytest.mark.asyncio
    async def test_force_stop_after_max_warnings(self):
        cb = RepetitionGuardCallback(_make_config(max_warnings=1))
        runtime = Runtime()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
        ]
        for i in range(3):
            msgs.append(
                _assistant_with_tools(
                    _tool_call("shell", {"command": "make build"}, f"c{i}")
                )
            )
            msgs.append(_tool_result(f"c{i}", "error"))

        await cb.after_tool_call(runtime, msgs)
        assert cb._warnings_given == 1

        msgs.append(
            _assistant_with_tools(
                _tool_call("shell", {"command": "make build"}, "c99")
            )
        )
        msgs.append(_tool_result("c99", "error"))

        await cb.after_tool_call(runtime, msgs)
        assert runtime.should_stop is True

    @pytest.mark.asyncio
    async def test_does_not_warn_same_key_twice(self):
        cb = RepetitionGuardCallback(_make_config())
        runtime = Runtime()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
        ]
        for i in range(4):
            msgs.append(
                _assistant_with_tools(
                    _tool_call("shell", {"command": "ls"}, f"c{i}")
                )
            )
            msgs.append(_tool_result(f"c{i}"))

        await cb.after_tool_call(runtime, msgs)
        assert cb._warnings_given == 1

        await cb.after_tool_call(runtime, msgs)
        assert cb._warnings_given == 1

    @pytest.mark.asyncio
    async def test_warns_on_new_pattern(self):
        cb = RepetitionGuardCallback(_make_config())
        runtime = Runtime()
        msgs = [
            Message(role="system", content="sys"),
            Message(role="user", content="do something"),
        ]
        for i in range(3):
            msgs.append(
                _assistant_with_tools(
                    _tool_call("shell", {"command": "ls"}, f"c{i}")
                )
            )
            msgs.append(_tool_result(f"c{i}"))

        await cb.after_tool_call(runtime, msgs)
        assert cb._warnings_given == 1

        for i in range(3):
            msgs.append(
                _assistant_with_tools(
                    _tool_call("shell", {"command": "pwd"}, f"d{i}")
                )
            )
            msgs.append(_tool_result(f"d{i}"))

        await cb.after_tool_call(runtime, msgs)
        assert cb._warnings_given == 2

    @pytest.mark.asyncio
    async def test_default_config(self):
        cb = RepetitionGuardCallback(DictConfig({}))
        assert cb.threshold == 3
        assert cb.lookback == 8
        assert cb.max_warnings == 2
