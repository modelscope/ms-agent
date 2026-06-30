"""Callback that detects stuck loops and injects strategy-variation prompts.

When the agent repeats the same tool call (same name + same arguments) multiple
times without making progress, this callback injects a user message encouraging
a different approach.  After ``max_warnings`` injections, the callback forces
the agent to stop to avoid wasting remaining API budget.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import List

from omegaconf import DictConfig

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks.base import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger

logger = get_logger()

_DEFAULT_THRESHOLD = 3
_DEFAULT_LOOKBACK = 8
_DEFAULT_MAX_WARNINGS = 2

_STRATEGY_PROMPT = (
    "IMPORTANT: You have been repeating the same approach multiple times "
    "without making progress. The exact same tool call or command has been "
    "attempted {count} times with the same arguments.\n\n"
    "Repeated action: {description}\n\n"
    "Please try a fundamentally different strategy. Consider:\n"
    "1. Check whether the prerequisites for your approach are actually met.\n"
    "2. Break the problem into smaller, verifiable sub-steps.\n"
    "3. Use a different tool or a different command to achieve the same goal.\n"
    "4. Read error messages carefully — they often suggest specific fixes.\n"
    "5. If a dependency is missing, install it before retrying.\n\n"
    "Do NOT repeat the same command again."
)

_FORCE_STOP_PROMPT = (
    "You have been warned multiple times about repeating the same approach, "
    "but continue to retry the same failing action. "
    "To conserve resources, execution is being stopped. "
    "Please review the errors above and formulate a new plan before "
    "the next attempt."
)


@dataclass(frozen=True)
class _Repetition:
    key: str
    tool_name: str
    count: int
    description: str


def _args_hash(arguments: str) -> str:
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (json.JSONDecodeError, TypeError):
        parsed = arguments
    canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()[:12]


class RepetitionGuardCallback(Callback):
    """Detects stuck loops and injects strategy-variation prompts."""

    def __init__(self, config: DictConfig) -> None:
        super().__init__(config)
        guard_cfg = getattr(config, "repetition_guard", None)
        if guard_cfg is None:
            guard_cfg = {}
        self.threshold: int = int(getattr(guard_cfg, "threshold", _DEFAULT_THRESHOLD))
        self.lookback: int = int(getattr(guard_cfg, "lookback_rounds", _DEFAULT_LOOKBACK))
        self.max_warnings: int = int(getattr(guard_cfg, "max_warnings", _DEFAULT_MAX_WARNINGS))
        self._warnings_given: int = 0
        self._warned_keys: set[str] = set()

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]) -> None:
        if self._warnings_given >= self.max_warnings:
            logger.info(
                "[RepetitionGuard] Max warnings (%d) reached — forcing stop.",
                self.max_warnings,
            )
            messages.append(Message(role="user", content=_FORCE_STOP_PROMPT))
            runtime.should_stop = True
            return

        recent = _extract_recent_tool_calls(messages, self.lookback)
        repetition = _detect_repetition(recent, self.threshold)

        if repetition is None:
            return
        if repetition.key in self._warned_keys:
            return

        self._warned_keys.add(repetition.key)
        self._warnings_given += 1
        logger.info(
            "[RepetitionGuard] Stuck loop detected (%s, %dx). Injecting strategy prompt. "
            "Warning %d/%d.",
            repetition.tool_name,
            repetition.count,
            self._warnings_given,
            self.max_warnings,
        )
        runtime.should_stop = False
        prompt = _STRATEGY_PROMPT.format(
            count=repetition.count,
            description=repetition.description,
        )
        messages.append(Message(role="user", content=prompt))


def _extract_recent_tool_calls(
    messages: List[Message],
    lookback: int,
) -> list[tuple[str, str, str]]:
    """Return ``(tool_name, args_hash, description)`` for recent rounds.

    Walks backwards through *messages* collecting assistant tool-call entries.
    Stops after scanning *lookback* assistant-with-tool-calls messages.
    """
    calls: list[tuple[str, str, str]] = []
    rounds_seen = 0

    for msg in reversed(messages):
        if rounds_seen >= lookback:
            break
        if msg.role == "assistant" and msg.tool_calls:
            rounds_seen += 1
            for tc in msg.tool_calls:
                name = tc.get("tool_name", "")
                raw_args = tc.get("arguments", "{}")
                ah = _args_hash(raw_args)
                desc = _summarize_call(name, raw_args)
                calls.append((name, ah, desc))

    return calls


def _detect_repetition(
    calls: list[tuple[str, str, str]],
    threshold: int,
) -> _Repetition | None:
    if not calls:
        return None

    key_counts: Counter[str] = Counter()
    key_to_info: dict[str, tuple[str, str]] = {}

    for name, ah, desc in calls:
        key = f"{name}:{ah}"
        key_counts[key] += 1
        if key not in key_to_info:
            key_to_info[key] = (name, desc)

    most_common_key, count = key_counts.most_common(1)[0]
    if count < threshold:
        return None

    tool_name, description = key_to_info[most_common_key]
    return _Repetition(
        key=most_common_key,
        tool_name=tool_name,
        count=count,
        description=description,
    )


def _summarize_call(tool_name: str, raw_args: str) -> str:
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
    except (json.JSONDecodeError, TypeError):
        args = raw_args

    if isinstance(args, dict) and "command" in args:
        cmd = str(args["command"])
        if len(cmd) > 120:
            cmd = cmd[:120] + "..."
        return f"{tool_name}(command={cmd})"

    summary = json.dumps(args, ensure_ascii=False)
    if len(summary) > 120:
        summary = summary[:120] + "..."
    return f"{tool_name}({summary})"
