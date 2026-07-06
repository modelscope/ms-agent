"""Hook executor dispatcher."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from ms_agent.hooks.events import HookResult
from ms_agent.hooks.executors.command import CommandHookExecutor, HookExecutionContext
from ms_agent.hooks.registry import HookHandlerConfig
from ms_agent.hooks.response_adapter import ResponseAdapter

OnHandlerComplete = Callable[
    [HookHandlerConfig, HookResult, float],
    Awaitable[None],
]


class HookExecutor:
    """Route hook handlers to backends by type."""

    def __init__(
        self,
        working_dir: str | None = None,
        *,
        command: CommandHookExecutor | None = None,
        response_adapter: ResponseAdapter | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
        fail_closed: bool = False,
    ) -> None:
        adapter = response_adapter or ResponseAdapter()
        self._backends: dict[str, Any] = {}
        if 'command' in enabled_executors:
            self._backends['command'] = command or CommandHookExecutor(
                working_dir=working_dir,
                response_adapter=adapter,
                fail_closed=fail_closed,
            )
        self._ctx: HookExecutionContext | None = None

    def set_context(self, ctx: HookExecutionContext) -> None:
        self._ctx = ctx

    async def execute(
        self,
        handler: HookHandlerConfig,
        event_data: dict[str, Any],
        ctx: HookExecutionContext | None = None,
    ) -> HookResult:
        backend = self._backends.get(handler.type)
        if backend is None:
            return HookResult(
                action='error',
                reason=f"Hook type '{handler.type}' not enabled",
            )
        return await backend.execute(handler, event_data, ctx or self._ctx)

    async def execute_all(
        self,
        handlers: list[HookHandlerConfig],
        event_data: dict[str, Any],
        *,
        blockable: bool = False,
        ctx: HookExecutionContext | None = None,
        on_handler_complete: OnHandlerComplete | None = None,
    ) -> HookResult:
        merged_context_parts: list[str] = []
        final_updated_args: dict[str, Any] | None = None
        aggregated_action: str | None = None
        exec_ctx = ctx or self._ctx

        def _merge_action(current: str | None, new: str) -> str | None:
            if new in ('deny', 'block'):
                return 'deny'
            if new == 'ask' and current != 'deny':
                return 'ask'
            if new == 'allow' and current is None:
                return 'allow'
            return current

        for handler in handlers:
            started = time.perf_counter()
            result = await self.execute(
                handler,
                event_data,
                _context_for_handler(exec_ctx, handler),
            )
            duration_ms = (time.perf_counter() - started) * 1000.0
            if on_handler_complete is not None:
                await on_handler_complete(handler, result, duration_ms)

            if result.additional_context:
                merged_context_parts.append(result.additional_context)

            if blockable and result.action in ('deny', 'block'):
                return HookResult(
                    action=result.action if result.action == 'block' else 'deny',
                    reason=result.reason,
                    additional_context='\n'.join(merged_context_parts),
                    updated_args=result.updated_args or final_updated_args,
                    exit_code=result.exit_code,
                    stderr=result.stderr,
                )

            aggregated_action = _merge_action(aggregated_action, result.action)

            if result.updated_args is not None:
                final_updated_args = result.updated_args
                event_data = {**event_data, 'tool_args': result.updated_args}
                if 'tool_input' in event_data:
                    event_data['tool_input'] = result.updated_args

        if aggregated_action is None:
            aggregated_action = 'pass'

        return HookResult(
            action=aggregated_action,
            additional_context='\n'.join(merged_context_parts),
            updated_args=final_updated_args,
        )


def _context_for_handler(
    ctx: HookExecutionContext | None,
    handler: HookHandlerConfig,
) -> HookExecutionContext | None:
    if ctx is None:
        return None
    if not handler.source_plugin_root and not handler.source_plugin_data_dir:
        return ctx
    return HookExecutionContext(
        session_id=ctx.session_id,
        project_path=ctx.project_path,
        plugin_root=handler.source_plugin_root or ctx.plugin_root,
        plugin_data_dir=handler.source_plugin_data_dir or ctx.plugin_data_dir,
        llm=ctx.llm,
        messages=ctx.messages,
        abort_signal=ctx.abort_signal,
        tool_manager=ctx.tool_manager,
    )
