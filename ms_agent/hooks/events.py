"""Canonical hook events and unified result envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SessionStartEvent:
    session_id: str
    project_path: str = ''
    event: str = field(default='SessionStart', init=False)


@dataclass(frozen=True)
class PreToolUseEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    event: str = field(default='PreToolUse', init=False)


@dataclass(frozen=True)
class PostToolUseEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result: str = ''
    event: str = field(default='PostToolUse', init=False)


@dataclass(frozen=True)
class UserPromptSubmitEvent:
    session_id: str
    prompt: str
    event: str = field(default='UserPromptSubmit', init=False)


@dataclass(frozen=True)
class StopEvent:
    session_id: str
    reason: str = ''
    last_assistant_message: str = ''
    stop_hook_active: bool = False
    event: str = field(default='Stop', init=False)


@dataclass(frozen=True)
class PermissionRequestEvent:
    session_id: str
    tool_name: str
    tool_args: dict[str, Any] = field(default_factory=dict)
    event: str = field(default='PermissionRequest', init=False)


@dataclass(frozen=True)
class HookResult:
    action: str  # allow | deny | ask | block | pass | error
    reason: str = ''
    additional_context: str = ''
    updated_args: dict[str, Any] | None = None
    exit_code: int = 0
    stderr: str = ''
