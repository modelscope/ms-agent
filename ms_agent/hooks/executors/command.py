"""Command hook executor — subprocess stdin/stdout protocol."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from dataclasses import dataclass
from typing import Any

from ms_agent.hooks.events import HookResult
from ms_agent.hooks.registry import HookHandlerConfig
from ms_agent.hooks.response_adapter import ResponseAdapter
from ms_agent.utils import get_logger

logger = get_logger()


@dataclass
class HookExecutionContext:
    session_id: str
    project_path: str
    plugin_root: str | None = None
    plugin_data_dir: str | None = None
    llm: Any | None = None
    messages: list | None = None
    abort_signal: asyncio.Event | None = None
    tool_manager: Any | None = None


def plugin_compat_payload(
    event_data: dict[str, Any],
    ctx: HookExecutionContext | None,
) -> dict[str, Any]:
    """Adapt MS-Agent hook payloads for Claude-format plugin scripts."""
    if ctx is None or not ctx.plugin_root:
        return event_data
    payload = dict(event_data)
    claude_tool = payload.get('tool_name_claude')
    if claude_tool:
        payload['tool_name'] = claude_tool
    payload.setdefault(
        'hook_event_name',
        payload.get('event') or payload.get('hook_event_name', ''),
    )
    if payload.get('event') == 'UserPromptSubmit':
        payload.setdefault('user_prompt', payload.get('prompt', ''))
    return payload


def build_hook_env(ctx: HookExecutionContext) -> dict[str, str]:
    env = dict(os.environ)
    env['MS_AGENT_PROJECT_DIR'] = ctx.project_path
    env['CLAUDE_PROJECT_DIR'] = ctx.project_path
    if ctx.plugin_root:
        env['MS_AGENT_PLUGIN_ROOT'] = ctx.plugin_root
        env['CLAUDE_PLUGIN_ROOT'] = ctx.plugin_root
    if ctx.plugin_data_dir:
        env['MS_AGENT_PLUGIN_DATA'] = ctx.plugin_data_dir
        env['CLAUDE_PLUGIN_DATA'] = ctx.plugin_data_dir
    if ctx.session_id:
        env['MS_AGENT_SESSION_ID'] = ctx.session_id
    return env


class CommandHookExecutor:
    def __init__(
        self,
        working_dir: str | None = None,
        response_adapter: ResponseAdapter | None = None,
        fail_closed: bool = False,
    ) -> None:
        self._working_dir = working_dir
        self._response_adapter = response_adapter or ResponseAdapter()
        self._fail_closed = fail_closed

    async def execute(
        self,
        handler: HookHandlerConfig,
        event_data: dict[str, Any],
        ctx: HookExecutionContext,
    ) -> HookResult:
        payload = plugin_compat_payload(event_data, ctx)
        stdin_data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *shlex.split(handler.command or ''),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                env=build_hook_env(ctx),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=handler.timeout,
            )
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass
            reason = f'Hook timed out after {handler.timeout}s'
            if handler.fail_closed or self._fail_closed:
                return HookResult(action='deny', reason=reason, exit_code=-1)
            return HookResult(action='error', reason=reason, exit_code=-1)
        except FileNotFoundError:
            reason = f'Hook command not found: {handler.command}'
            if handler.fail_closed or self._fail_closed:
                return HookResult(action='deny', reason=reason, exit_code=-1)
            return HookResult(action='error', reason=reason, exit_code=-1)
        except Exception as e:
            reason = str(e)
            if handler.fail_closed or self._fail_closed:
                return HookResult(action='deny', reason=reason, exit_code=-1)
            return HookResult(action='error', reason=reason, exit_code=-1)

        exit_code = proc.returncode or 0
        stderr_text = stderr.decode('utf-8', errors='replace').strip()
        stdout_text = stdout.decode('utf-8', errors='replace').strip()

        if exit_code == 2:
            return HookResult(
                action='deny',
                reason=stderr_text or 'Blocked by hook',
                exit_code=exit_code,
                stderr=stderr_text,
            )

        if exit_code != 0:
            logger.warning(
                "Hook '%s' exited %d: %s", handler.command, exit_code, stderr_text)
            if handler.fail_closed or self._fail_closed:
                return HookResult(
                    action='deny',
                    reason=stderr_text or f'Hook exited {exit_code}',
                    exit_code=exit_code,
                    stderr=stderr_text,
                )
            return HookResult(
                action='error',
                reason=stderr_text,
                exit_code=exit_code,
                stderr=stderr_text,
            )

        return self._response_adapter.parse(
            stdout_text, exit_code, stderr_text, event_data.get('event'))
