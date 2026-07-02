# Copyright (c) ModelScope Contributors. All rights reserved.
"""MCP runtime state machine and ToolManager synchronization."""
from __future__ import annotations

import asyncio
import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Literal, Optional, TYPE_CHECKING

from ms_agent.config.mcp_schema import (
    ResolvedMCPConfig,
    connection_params_for_client,
)
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.utils import enhance_error, get_logger

if TYPE_CHECKING:
    from ms_agent.tools.tool_manager import ToolManager

logger = get_logger()

MCPServerStatus = Literal[
    'registered',
    'connecting',
    'connected',
    'degraded',
    'error',
    'disabled',
]

FAILURE_HISTORY_LIMIT = 20
# Transient failures (timeout / 5xx) must reach this count before degraded.
DEGRADED_FAILURE_THRESHOLD = 3

MCPFailureKind = Literal['none', 'transient', 'hard']


@dataclass
class MCPFailureRecord:
    """Single failure snapshot (in-memory, for UI / diagnostics)."""

    at: str
    phase: Literal['connect', 'call_tool', 'list_tools']
    message: str
    tool_name: str | None = None


@dataclass
class MCPServerState:
    name: str
    config: dict
    enabled: bool
    status: MCPServerStatus
    last_error: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    consecutive_failures: int = 0
    failure_history: Deque[MCPFailureRecord] = field(
        default_factory=lambda: deque(maxlen=FAILURE_HISTORY_LIMIT))
    tool_count: int = 0
    cached_tools: list[dict] = field(default_factory=list)
    connected_at: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_mcp_failure(exc: BaseException) -> MCPFailureKind:
    """Classify transport failures for degraded policy.

    - ``hard``: session/process gone — degrade immediately.
    - ``transient``: timeout / upstream 5xx — may be jitter; degrade only
      after ``DEGRADED_FAILURE_THRESHOLD`` consecutive failures.
    - ``none``: business / argument errors — do not change ``status``.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return 'transient'
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return 'hard'
    if isinstance(exc, ConnectionError):
        return 'hard'
    msg = str(exc).lower()
    hard_markers = (
        'connection closed',
        'session closed',
        'broken pipe',
        'disconnected',
        'connection refused',
    )
    if any(m in msg for m in hard_markers):
        return 'hard'
    transient_markers = (
        'timeout',
        'timed out',
        '502',
        '503',
    )
    if any(m in msg for m in transient_markers):
        return 'transient'
    return 'none'


def classify_failure_message(message: str) -> MCPFailureKind:
    """Message-only fallback when the original exception is unavailable."""
    return classify_mcp_failure(Exception(message))


def is_connection_error(exc: BaseException) -> bool:
    """Whether a tool exception should be reported to MCP failure tracking."""
    return classify_mcp_failure(exc) in ('transient', 'hard')


class MCPRuntime:
    """Configuration-driven MCP lifecycle and ToolManager sync."""

    def __init__(
        self,
        *,
        mcp_client: MCPClient | None = None,
        config: ResolvedMCPConfig | None = None,
        owns_client: bool | None = None,
        connect_policy: Literal['skip', 'fail_fast'] = 'skip',
    ):
        self._config = config
        self._connect_policy = connect_policy
        self._states: Dict[str, MCPServerState] = {}
        self._tool_manager: ToolManager | None = None
        self._sync_lock = asyncio.Lock()
        self._started = False

        if mcp_client is not None:
            self._client = mcp_client
            self._owns_client = (
                owns_client if owns_client is not None else False)
        else:
            mcp_json = config.to_mcp_json() if config else None
            self._client = MCPClient(mcp_config=mcp_json)
            self._owns_client = True

        if config is not None:
            self._register_from_config(config)

    @property
    def client(self) -> MCPClient:
        return self._client

    @property
    def is_started(self) -> bool:
        return self._started

    # ── lifecycle ──────────────────────────────────────────────────────

    def _register_from_config(self, config: ResolvedMCPConfig) -> None:
        for name, server_cfg in config.mcp_servers.items():
            enabled = bool(server_cfg.get('enabled', True))
            status: MCPServerStatus = 'disabled' if not enabled else 'registered'
            self._states[name] = MCPServerState(
                name=name,
                config=copy.deepcopy(server_cfg),
                enabled=enabled,
                status=status,
            )

    async def start(self) -> None:
        """Connect all enabled servers (idempotent)."""
        async with self._sync_lock:
            self._started = True
            failures: list[BaseException] = []
            for name, state in self._states.items():
                if not state.enabled:
                    state.status = 'disabled'
                    continue
                if self._client.is_connected(name):
                    if state.status != 'connected':
                        state.status = 'connected'
                    continue
                try:
                    await self._connect_server(name, state)
                except Exception as exc:
                    if self._connect_policy == 'fail_fast':
                        raise
                    failures.append(exc)
            if failures and self._connect_policy == 'fail_fast':
                raise failures[0]

    async def stop(self) -> None:
        """Disconnect all servers when this runtime owns the client."""
        async with self._sync_lock:
            self._started = False
            if self._owns_client:
                await self._client.cleanup()
            for state in self._states.values():
                if state.enabled:
                    state.status = 'registered'
                else:
                    state.status = 'disabled'
                state.cached_tools.clear()
                state.tool_count = 0
                state.connected_at = None

    async def _connect_server(self, name: str, state: MCPServerState) -> None:
        state.status = 'connecting'
        state.last_error = None
        try:
            await self._client.connect_single_server(
                name, connection_params_for_client(state.config))
            state.status = 'connected'
            state.connected_at = _utc_now()
            state.last_success_at = state.connected_at
            state.consecutive_failures = 0
            await self._refresh_cached_tools(name, state)
        except Exception as exc:
            new_exc = enhance_error(exc, f'Connect `{name}` failed, details:')
            await self._record_connect_failure(name, str(new_exc))
            if self._connect_policy == 'fail_fast':
                raise new_exc from exc

    async def _refresh_cached_tools(
        self,
        name: str,
        state: MCPServerState,
    ) -> None:
        try:
            tools = await self._client.get_tools_for_server(name)
            state.cached_tools = [dict(t) for t in tools]
            state.tool_count = len(state.cached_tools)
            state.last_success_at = _utc_now()
        except Exception as exc:
            await self.record_failure(
                name, 'list_tools', str(exc), exc=exc)

    # ── enable / disable ───────────────────────────────────────────────

    async def enable_server(self, name: str) -> MCPServerState:
        async with self._sync_lock:
            return await self._enable_server_unlocked(name)

    async def _enable_server_unlocked(self, name: str) -> MCPServerState:
        state = self._require_state(name)
        state.enabled = True
        state.config['enabled'] = True
        if not self._client.is_connected(name):
            await self._connect_server(name, state)
        elif state.status in ('registered', 'disabled', 'error'):
            state.status = 'connected'
        await self._sync_tools_unlocked()
        return state

    async def disable_server(self, name: str) -> MCPServerState:
        async with self._sync_lock:
            return await self._disable_server_unlocked(name)

    async def _disable_server_unlocked(self, name: str) -> MCPServerState:
        state = self._require_state(name)
        state.enabled = False
        state.config['enabled'] = False
        state.status = 'disabled'
        state.cached_tools.clear()
        state.tool_count = 0
        await self._sync_tools_unlocked()
        return state

    async def reload_server(self, name: str) -> MCPServerState:
        async with self._sync_lock:
            await self._disable_server_unlocked(name)
            state = self._require_state(name)
            state.enabled = True
            state.config['enabled'] = True
            if self._client.is_connected(name):
                await self._client.disconnect_server(name)
            await self._connect_server(name, state)
            await self._sync_tools_unlocked()
            return state

    async def reconnect_server(self, name: str) -> MCPServerState:
        async with self._sync_lock:
            state = self._require_state(name)
            if not state.enabled:
                raise ValueError(f'Server {name} is disabled')
            if self._client.is_connected(name):
                await self._client.disconnect_server(name)
            state.status = 'registered'
            state.cached_tools.clear()
            state.tool_count = 0
            await self._connect_server(name, state)
            await self._sync_tools_unlocked()
            return state

    # ── config hot update ──────────────────────────────────────────────

    async def apply_config(self, config: ResolvedMCPConfig) -> list[MCPServerState]:
        async with self._sync_lock:
            self._config = config
            old_names = set(self._states)
            new_names = set(config.mcp_servers)
            removed = old_names - new_names
            added = new_names - old_names
            changed = {
                n for n in old_names & new_names
                if self._states[n].config != config.mcp_servers[n]
            }

            for name in removed:
                if self._client.is_connected(name):
                    await self._client.disconnect_server(name)
                if name in self._states:
                    state = self._states[name]
                    state.enabled = False
                    state.status = 'disabled'
                    state.cached_tools.clear()
                    state.tool_count = 0
                self._states.pop(name, None)

            for name in added:
                entry = copy.deepcopy(config.mcp_servers[name])
                enabled = bool(entry.get('enabled', True))
                self._states[name] = MCPServerState(
                    name=name,
                    config=entry,
                    enabled=enabled,
                    status='disabled' if not enabled else 'registered',
                )

            for name in changed:
                state = self._states[name]
                old_enabled = state.enabled
                state.config = copy.deepcopy(config.mcp_servers[name])
                state.enabled = bool(state.config.get('enabled', True))
                if not state.enabled:
                    state.status = 'disabled'
                    state.cached_tools.clear()
                    state.tool_count = 0
                elif old_enabled != state.enabled or name in changed:
                    if self._client.is_connected(name):
                        await self._client.disconnect_server(name)
                    state.status = 'registered'

            for name, state in self._states.items():
                if not state.enabled:
                    continue
                if not self._client.is_connected(name):
                    try:
                        await self._connect_server(name, state)
                    except Exception:
                        if self._connect_policy == 'fail_fast':
                            raise
                elif name in changed:
                    await self._refresh_cached_tools(name, state)

            await self._sync_tools_unlocked()
            return list(self._states.values())

    # ── query ──────────────────────────────────────────────────────────

    def list_servers(self) -> list[MCPServerState]:
        return list(self._states.values())

    def get_server(self, name: str) -> MCPServerState | None:
        return self._states.get(name)

    def is_callable(self, server_name: str) -> bool:
        state = self._states.get(server_name)
        return state is not None and state.status == 'connected'

    def unavailable_detail(self, server_name: str) -> dict:
        state = self._states.get(server_name)
        if state is None:
            return {
                'success': False,
                'error': 'mcp_unavailable',
                'server_name': server_name,
                'message': f'Unknown MCP server: {server_name}',
            }
        return {
            'success': False,
            'error': 'mcp_unavailable',
            'server_name': server_name,
            'status': state.status,
            'message': state.last_error or (
                f'MCP server {server_name} is not callable (status={state.status})'
            ),
        }

    # ── failure tracking ───────────────────────────────────────────────

    async def record_failure(
        self,
        name: str,
        phase: str,
        message: str,
        *,
        tool_name: str | None = None,
        exc: BaseException | None = None,
    ) -> None:
        async with self._sync_lock:
            degraded = self._apply_failure_state(
                name, phase, message, tool_name=tool_name, exc=exc)
            if degraded:
                await self._sync_tools_unlocked()

    def _apply_failure_state(
        self,
        name: str,
        phase: str,
        message: str,
        *,
        tool_name: str | None = None,
        exc: BaseException | None = None,
    ) -> bool:
        """Update failure counters; return True if status became degraded."""
        state = self._states.get(name)
        if state is None:
            return False
        failure_kind = (
            classify_mcp_failure(exc) if exc is not None
            else classify_failure_message(message))
        if failure_kind == 'none':
            return False
        now = _utc_now()
        record = MCPFailureRecord(
            at=now,
            phase=phase,  # type: ignore[arg-type]
            message=message,
            tool_name=tool_name,
        )
        state.failure_history.append(record)
        state.last_error = message
        state.last_failure_at = now
        state.consecutive_failures += 1
        should_degrade = (
            failure_kind == 'hard'
            or state.consecutive_failures >= DEGRADED_FAILURE_THRESHOLD
        )
        if should_degrade and state.status == 'connected':
            state.status = 'degraded'
            return True
        return False

    async def record_success(self, name: str) -> None:
        """Reset failure counters after a successful MCP RPC."""
        async with self._sync_lock:
            state = self._states.get(name)
            if state is None:
                return
            state.consecutive_failures = 0
            state.last_success_at = _utc_now()

    async def _record_connect_failure(self, name: str, message: str) -> None:
        state = self._states.get(name)
        if state is None:
            return
        state.status = 'error'
        state.last_error = message
        state.last_failure_at = _utc_now()
        state.consecutive_failures += 1
        state.failure_history.append(
            MCPFailureRecord(
                at=state.last_failure_at,
                phase='connect',
                message=message,
            ))

    # ── ToolManager integration ────────────────────────────────────────

    def bind_tool_manager(self, tool_manager: 'ToolManager') -> None:
        self._tool_manager = tool_manager

    async def sync_tools(self) -> None:
        async with self._sync_lock:
            await self._sync_tools_unlocked()

    async def _sync_tools_unlocked(self) -> None:
        if self._tool_manager is None:
            return
        indexable: set[str] = set()
        callable_servers: set[str] = set()
        for name, state in self._states.items():
            if not state.enabled:
                continue
            if state.status == 'connected':
                indexable.add(name)
                callable_servers.add(name)
        failures = await self._tool_manager.sync_mcp_tools(
            visible_servers=set(self._states.keys()),
            indexable_servers=indexable,
            callable_servers=callable_servers,
            cached_tools_by_server=None,
        )
        needs_resync = False
        for server_name, exc in failures:
            if self._apply_failure_state(
                    server_name,
                    'list_tools',
                    str(exc),
                    exc=exc,
            ):
                needs_resync = True
        if needs_resync:
            await self._sync_tools_unlocked()

    def _require_state(self, name: str) -> MCPServerState:
        state = self._states.get(name)
        if state is None:
            raise KeyError(f'Unknown MCP server: {name}')
        return state
