"""HookRuntime facade — registry + executor + payload building."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable

from ms_agent.hooks.context import HookAttachment
from ms_agent.hooks.events import (
    HookResult,
    PermissionRequestEvent,
    PostToolUseEvent,
    PreToolUseEvent,
    SessionStartEvent,
    StopEvent,
    UserPromptSubmitEvent,
)
from ms_agent.hooks.executor import HookExecutor
from ms_agent.hooks.executors.command import HookExecutionContext
from ms_agent.hooks.registry import HookHandlerConfig, HookRegistry
from ms_agent.hooks.tool_name_mapper import ToolNameMapper

HookEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def _handler_name(handler: HookHandlerConfig) -> str:
    if handler.command:
        return handler.command
    if handler.url:
        return handler.url
    return handler.type


@dataclass
class HookRuntime:
    registry: HookRegistry
    executor: HookExecutor
    session_id: str
    project_path: str
    tool_name_mapper: ToolNameMapper
    on_hook_event: HookEventCallback | None = None
    default_model: str = 'qwen-plus'

    BLOCKABLE_EVENTS = frozenset({
        'PreToolUse', 'UserPromptSubmit', 'Stop', 'PermissionRequest',
    })

    @property
    def is_empty(self) -> bool:
        return self.registry.is_empty

    @property
    def has_session_handlers(self) -> bool:
        return bool(self.registry.get_handlers('SessionStart'))

    def _ctx(self) -> HookExecutionContext:
        return HookExecutionContext(
            session_id=self.session_id,
            project_path=self.project_path,
        )

    def _build_payload(self, event_obj: Any) -> dict[str, Any]:
        payload = asdict(event_obj)
        payload['project_path'] = self.project_path
        payload['cwd'] = self.project_path
        payload.setdefault('extra', {})
        if 'tool_args' in payload:
            payload.setdefault('tool_input', payload['tool_args'])
        return self.tool_name_mapper.enrich_payload(
            payload, payload.get('tool_name'))

    async def _notify_hook_event(
        self,
        *,
        hook_event: str,
        handler: HookHandlerConfig,
        result: HookResult,
        duration_ms: float,
    ) -> None:
        if self.on_hook_event is None:
            return
        await self.on_hook_event({
            'hook_event': hook_event,
            'hook_name': _handler_name(handler),
            'action': result.action,
            'reason': result.reason,
            'duration_ms': duration_ms,
        })

    async def _run_event(
        self,
        event_type: str,
        event_obj: Any,
        tool_name: str | None = None,
    ) -> HookResult:
        handlers = self.registry.get_handlers(event_type, tool_name)
        if not handlers:
            return HookResult(action='pass')

        payload = self._build_payload(event_obj)
        blockable = event_type in self.BLOCKABLE_EVENTS

        async def _on_handler_complete(
            handler: HookHandlerConfig,
            result: HookResult,
            duration_ms: float,
        ) -> None:
            await self._notify_hook_event(
                hook_event=event_type,
                handler=handler,
                result=result,
                duration_ms=duration_ms,
            )

        result = await self.executor.execute_all(
            handlers,
            payload,
            blockable=blockable,
            ctx=self._ctx(),
            on_handler_complete=_on_handler_complete,
        )

        # Stop: map deny to block for continuation semantics (§9.4)
        if event_type == 'Stop' and result.action == 'deny':
            result = HookResult(
                action='block',
                reason=result.reason,
                additional_context=result.additional_context,
                updated_args=result.updated_args,
                exit_code=result.exit_code,
                stderr=result.stderr,
            )

        return result

    @staticmethod
    def _attachments_for_context(
        hook_event: str,
        result: HookResult,
        *,
        tool_call_id: str | None = None,
    ) -> list[HookAttachment]:
        if not result.additional_context:
            return []
        return [
            HookAttachment(
                type='hook_additional_context',
                hook_event=hook_event,
                tool_call_id=tool_call_id,
                content=result.additional_context,
            ),
        ]

    async def run_session_start(self, runtime: Any, messages: list) -> HookResult:
        return await self._run_event(
            'SessionStart',
            SessionStartEvent(
                session_id=self.session_id,
                project_path=self.project_path,
            ),
        )

    async def run_pre_tool_use(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        session_id: str | None = None,
        project_path: str | None = None,
    ) -> tuple[HookResult, list[HookAttachment]]:
        result = await self._run_event(
            'PreToolUse',
            PreToolUseEvent(
                session_id=session_id or self.session_id,
                tool_name=tool_name,
                tool_args=tool_args,
            ),
            tool_name=tool_name,
        )
        attachments = self._attachments_for_context(
            'PreToolUse',
            result,
            tool_call_id=None,
        )
        return result, attachments

    async def run_post_tool_use(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: str,
        *,
        tool_call_id: str | None = None,
    ) -> tuple[HookResult, list[HookAttachment]]:
        result = await self._run_event(
            'PostToolUse',
            PostToolUseEvent(
                session_id=self.session_id,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=tool_result,
            ),
            tool_name=tool_name,
        )
        attachments = self._attachments_for_context(
            'PostToolUse',
            result,
            tool_call_id=tool_call_id,
        )
        return result, attachments

    async def run_user_prompt_submit(self, prompt: str) -> HookResult:
        return await self._run_event(
            'UserPromptSubmit',
            UserPromptSubmitEvent(session_id=self.session_id, prompt=prompt),
        )

    async def run_permission_request(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> HookResult:
        return await self._run_event(
            'PermissionRequest',
            PermissionRequestEvent(
                session_id=self.session_id,
                tool_name=tool_name,
                tool_args=tool_args,
            ),
            tool_name=tool_name,
        )

    async def run_stop(
        self,
        reason: str = '',
        last_assistant_message: str = '',
        stop_hook_active: bool = False,
    ) -> HookResult:
        return await self._run_event(
            'Stop',
            StopEvent(
                session_id=self.session_id,
                reason=reason,
                last_assistant_message=last_assistant_message,
                stop_hook_active=stop_hook_active,
            ),
        )
