# Copyright (c) ModelScope Contributors. All rights reserved.
"""MCP runtime state machine and ToolManager synchronization."""
from __future__ import annotations

import asyncio
import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Literal, Optional

from ms_agent.config.mcp_schema import (ResolvedMCPConfig,
                                        connection_params_for_client)
from ms_agent.tools.mcp_client import (
    DEFAULT_SERVER_STARTUP_TIMEOUT,
    MCP_PROBE_TIMEOUT,
    MCPClient,
)
from ms_agent.utils import get_logger

if TYPE_CHECKING:
    from ms_agent.tools.tool_manager import ToolManager

logger = get_logger()

MCPServerStatus = Literal['registered', 'connecting', 'connected', 'degraded',
                          'error', 'disabled', ]

FAILURE_HISTORY_LIMIT = 20
# Transient failures (timeout / 5xx) must reach this count before degraded.
DEGRADED_FAILURE_THRESHOLD = 3
# How long a turn waits for a server that is already starting. A warm
# stdio process answers in about two seconds and joins this turn. Anything
# slower keeps going in the background; the next message picks it up.
MCP_TURN_WAIT = 3

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
    # The stdio child was observed gone. Stays set until a connect succeeds
    # so /mcp can say the process exited while a reconnect is in flight.
    process_exited: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exception_group_members(exc: BaseException):
    """Nested exceptions of an ExceptionGroup, on 3.11 and the 3.10 backport."""
    if type(exc).__name__ not in ('ExceptionGroup', 'BaseExceptionGroup'):
        return None
    members = getattr(exc, 'exceptions', None)
    if isinstance(members, tuple):
        return members
    return None


def classify_mcp_failure(exc: BaseException) -> MCPFailureKind:
    """Classify transport failures for degraded policy.

    - ``hard``: session/process gone — degrade immediately.
    - ``transient``: timeout / upstream 5xx — may be jitter; degrade only
      after ``DEGRADED_FAILURE_THRESHOLD`` consecutive failures.
    - ``none``: business / argument errors — do not change ``status``.
    """
    members = _exception_group_members(exc)
    if members is not None:
        kinds = [classify_mcp_failure(item) for item in members]
        if 'hard' in kinds:
            return 'hard'
        if 'transient' in kinds:
            return 'transient'
        return 'none'
    if isinstance(exc, asyncio.TimeoutError):
        return 'transient'
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return 'hard'
    if isinstance(exc, ConnectionError):
        return 'hard'
    type_name = type(exc).__name__.lower()
    if type_name in ('closedresourceerror', 'brokenresourceerror'):
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


def short_connect_reason(exc: BaseException, timeout: float) -> str:
    """One short clause for a connect that did not succeed."""
    if isinstance(exc, TimeoutError):
        label = str(int(timeout)) if timeout >= 1 else f'{timeout:g}'
        return f'{label}秒内没有连上'
    text = ' '.join(str(exc).split())
    if not text:
        text = type(exc).__name__
    if len(text) > 80:
        text = text[:79] + '…'
    return text


def mcp_unreachable_notice(name: str, reason: str) -> str:
    """The one line shown when a server is left out of this turn."""
    return f'MCP 服务器 {name} 连不上（{reason}），本轮先不用。'


def degraded_user_notice(
    server_name: str,
    exc: BaseException | None = None,
    message: str = '',
) -> str:
    """One sentence when a server has just become unusable.

    A second failure uses a different sentence, sent from the live-config
    sync, not from here.
    """
    del exc, message
    return f'MCP 服务器 {server_name} 连接断开，本轮对话无法使用。自动尝试重连中。'


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
        self._probe_tasks: Dict[str, asyncio.Task] = {}

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

    async def start(self, *, wait: bool = True) -> None:
        """Connect enabled servers.

        ``wait`` holds this call for ``MCP_TURN_WAIT`` so a server that is
        already up can join. The TUI passes ``False``: the prompt must not
        sit behind a cold ``npx``. The first message waits instead.

        A remote handshake still gives up after ``MCP_PROBE_TIMEOUT``. A
        stdio process keeps the real startup budget in the background.
        """
        async with self._sync_lock:
            self._started = True
            names: list[str] = []
            for name, state in self._states.items():
                if not state.enabled:
                    state.status = 'disabled'
                    continue
                if self._client.is_connected(name):
                    if state.status != 'connected':
                        state.status = 'connected'
                    continue
                names.append(name)
            await self._probe_servers(names, wait=wait)

    async def stop(self) -> None:
        """Disconnect all servers when this runtime owns the client."""
        await self._cancel_probes()
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

    def _connect_budget(self, state: MCPServerState) -> float:
        """Remote handshake stays short. stdio may spend the real startup."""
        config = state.config or {}
        if config.get('command') and not config.get('url'):
            return float(DEFAULT_SERVER_STARTUP_TIMEOUT)
        return float(MCP_PROBE_TIMEOUT)

    def _probe_running(self, name: str) -> bool:
        task = self._probe_tasks.get(name)
        return task is not None and not task.done()

    def _stdio_dead(self, name: str, state: MCPServerState) -> bool:
        """A connected stdio server whose child is already gone."""
        if state.status != 'connected':
            return False
        config = state.config or {}
        if not config.get('command') or config.get('url'):
            return False
        exited = getattr(self._client, 'stdio_process_exited', None)
        if exited is not None:
            try:
                if exited(name):
                    return True
            except Exception:
                logger.debug('stdio liveness check failed for %s',
                             name,
                             exc_info=True)
        tasks = getattr(self._client, '_server_tasks', None)
        if isinstance(tasks, dict):
            task = tasks.get(name)
            if task is not None and task.done():
                return True
        return not self._client.is_connected(name)

    async def _mark_dead_stdio(self) -> list[str]:
        """Drop a dead child from the tools and name it for one reconnect."""
        names: list[str] = []
        for name, state in self._states.items():
            if not self._stdio_dead(name, state):
                continue
            state.process_exited = True
            state.last_error = '进程已退出'
            state.cached_tools.clear()
            state.tool_count = 0
            state.status = 'registered'
            if self._client.is_connected(name):
                await self._drop_unfinished_connect(name)
            names.append(name)
        return names

    def _schedule_probes(self, names: list[str]) -> None:
        for name in names:
            state = self._states.get(name)
            if state is None or not state.enabled:
                continue
            if self._probe_running(name):
                continue
            timeout = self._connect_budget(state)
            task = asyncio.create_task(
                self._finish_connect(name, state, timeout),
                name=f'mcp-probe:{name}',
            )
            self._probe_tasks[name] = task
            task.add_done_callback(self._forget_probe)

    def _forget_probe(self, task: 'asyncio.Task') -> None:
        for name, current in list(self._probe_tasks.items()):
            if current is task:
                self._probe_tasks.pop(name, None)
                break
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None and self._connect_policy != 'fail_fast':
            logger.debug('MCP probe failed: %s', exc)

    async def _cancel_probes(self) -> None:
        tasks = list(self._probe_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _wait_probes(self) -> None:
        """Give in-flight connects a short chance to join this turn."""
        pending = [
            task for task in self._probe_tasks.values() if not task.done()
        ]
        if pending and MCP_TURN_WAIT > 0:
            await asyncio.wait(pending, timeout=MCP_TURN_WAIT)
        if self._connect_policy != 'fail_fast':
            return
        for task in list(self._probe_tasks.values()):
            if task.done() and not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    raise exc

    async def _probe_servers(
        self,
        names: list[str],
        *,
        wait: bool = True,
    ) -> None:
        """Start connects together. The turn waits only ``MCP_TURN_WAIT``.

        One slow server must not hold the others, and must not hold the turn
        for its whole startup budget.
        """
        self._schedule_probes(names)
        if wait:
            await self._wait_probes()
        else:
            await asyncio.sleep(0)

    async def _finish_connect(
        self,
        name: str,
        state: MCPServerState,
        timeout: float,
    ) -> None:
        if not state.enabled:
            return
        state.status = 'connecting'
        try:
            await asyncio.wait_for(
                self._client.connect_single_server(
                    name,
                    connection_params_for_client(state.config),
                    startup_timeout=timeout,
                ),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = short_connect_reason(exc, timeout)
            logger.warning('MCP server %s unreachable: %s', name, exc)
            await self._record_connect_failure(name, reason)
            await self._drop_unfinished_connect(name)
            if self._connect_policy == 'fail_fast':
                raise
            return
        state.status = 'connected'
        state.process_exited = False
        state.last_error = None
        state.connected_at = _utc_now()
        state.last_success_at = state.connected_at
        state.consecutive_failures = 0
        await self._refresh_cached_tools(name, state)

    async def _connect_server(self, name: str, state: MCPServerState) -> None:
        """Finish one connect. Enable and reconnect keep the short cap.

        The turn's background probe is the path that may spend the stdio
        startup budget. This one still gives up after ``MCP_PROBE_TIMEOUT``.
        """
        running = self._probe_tasks.get(name)
        if running is not None and not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
        await self._finish_connect(name, state, float(MCP_PROBE_TIMEOUT))

    async def refresh_for_turn(self, *, wait: bool = True) -> None:
        """Adopt finished connects and reconnect a stdio child that died.

        A server already marked failed stays failed. ``retry_server`` or a
        config edit is what tries it again. ``wait=False`` only reads the
        current processes, for ``/mcp list`` and ``/mcp get``.
        """
        async with self._sync_lock:
            names = await self._mark_dead_stdio()
            await self._probe_servers(names, wait=wait)
            await self._sync_tools_unlocked()

    async def retry_server(self, name: str) -> MCPServerState:
        """Try one failed server again. Does not block on a cold startup."""
        async with self._sync_lock:
            state = self._require_state(name)
            if not state.enabled:
                raise ValueError(f'Server {name} is disabled')
            running = self._probe_tasks.get(name)
            if running is not None and not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
            if self._client.is_connected(name):
                await self._drop_unfinished_connect(name)
            state.status = 'registered'
            state.cached_tools.clear()
            state.tool_count = 0
            self._schedule_probes([name])
            await self._wait_probes()
            await self._sync_tools_unlocked()
            return state

    async def _drop_unfinished_connect(self, name: str) -> None:
        """Stop a dial that the 6s cap abandoned, without the graceful wait."""
        disconnect = getattr(self._client, 'disconnect_server', None)
        if disconnect is None:
            return
        try:
            await disconnect(name, graceful=False)
        except TypeError:
            try:
                await disconnect(name)
            except Exception:
                logger.debug(
                    'stop unfinished MCP connect %s', name, exc_info=True)
        except Exception:
            logger.debug('stop unfinished MCP connect %s', name, exc_info=True)

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
            # Already inside the connect lock. record_failure would take it
            # again and deadlock when several servers list tools together.
            self._apply_failure_state(name, 'list_tools', str(exc), exc=exc)

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

    async def apply_config(
        self,
        config: ResolvedMCPConfig,
        *,
        wait: bool = True,
    ) -> list[MCPServerState]:
        async with self._sync_lock:
            self._config = config
            old_names = set(self._states)
            new_names = set(config.mcp_servers)
            removed = old_names - new_names
            added = new_names - old_names
            changed = {
                n
                for n in old_names & new_names
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

            await self._mark_dead_stdio()
            to_probe: list[str] = []
            for name, state in self._states.items():
                if not state.enabled:
                    continue
                # A degraded server may still hold a dead session. Drop it
                # so this apply reconnects instead of keeping the stale one.
                if (state.status == 'degraded'
                        and self._client.is_connected(name)):
                    await self._client.disconnect_server(name)
                    state.status = 'registered'
                if self._probe_running(name):
                    continue
                if not self._client.is_connected(name):
                    # Probed already for this config. The next message must
                    # not pay the timeout again; a config edit clears it.
                    if (state.status == 'error' and name not in added
                            and name not in changed):
                        continue
                    to_probe.append(name)
                elif name in changed:
                    await self._refresh_cached_tools(name, state)
            await self._probe_servers(to_probe, wait=wait)

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
            'success':
            False,
            'error':
            'mcp_unavailable',
            'server_name':
            server_name,
            'status':
            state.status,
            'message':
            state.last_error or
            (f'MCP server {server_name} is not callable (status={state.status})'
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
    ) -> bool:
        """Record one failure. Return True only when status just became degraded."""
        async with self._sync_lock:
            degraded = self._apply_failure_state(
                name, phase, message, tool_name=tool_name, exc=exc)
            if degraded:
                await self._sync_tools_unlocked()
            return degraded

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
            classify_mcp_failure(exc)
            if exc is not None else classify_failure_message(message))
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
            or state.consecutive_failures >= DEGRADED_FAILURE_THRESHOLD)
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
