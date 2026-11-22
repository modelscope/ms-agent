"""Independent MCP diagnostics; never used to choose a session's tools.

All probes and cache mutations run on the API loop. A command lookup is unknown,
not healthy. A connection test uses the SDK's complete startup path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import dataclass

from ms_agent.tools.mcp_client import (
    MCPClient, resolve_stdio_command, safe_mcp_error, stdio_child_env,
)

_TTL_OK = 60.0
_TTL_FAIL = 10.0


@dataclass(frozen=True)
class ProbeResult:
    healthy: bool | None
    error: str | None
    level: str
    checked_at: float
    expires_at: float

    def __iter__(self):
        yield self.healthy
        yield self.error


_cache: dict[tuple, ProbeResult] = {}
_inflight: dict[tuple, asyncio.Task] = {}
_generation = 0


def _ttl(ok: bool | None) -> float:
    return _TTL_FAIL if ok is False else _TTL_OK


def _runtime_view(server: dict) -> dict:
    from ms_agent.tui.managed_config import expand_env_placeholders

    resolved = expand_env_placeholders(server)
    if resolved.get('command'):
        resolved['env'] = stdio_child_env(MCPClient.resolve_server_env(resolved))
    return resolved


def _cache_key(name: str, server: dict, scope: str = 'global') -> tuple:
    # Secrets affect identity, but never appear in keys, logs or API metadata.
    payload = json.dumps(server, sort_keys=True, default=str).encode()
    return scope, name, hashlib.sha256(payload).hexdigest()


def _probe_stdio(server: dict) -> bool:
    if not server.get('command'):
        return True
    try:
        command = resolve_stdio_command(server['command'])
        import os
        return os.path.isfile(command) and os.access(command, os.X_OK)
    except (FileNotFoundError, TypeError):
        return False


async def _handshake(server: dict) -> bool:
    client = MCPClient()
    try:
        await client.connect_single_server('probe', server)
        return True
    except Exception as exc:
        reason = client.startup_failures.get('probe')
        if reason:
            raise RuntimeError(reason) from exc
        raise
    finally:
        await client.cleanup()


# Kept as separate seams for transport-specific regression tests.
_remote_handshake = _handshake
_stdio_handshake = _handshake


async def check_server(server: dict, timeout: float = 6.0,
                       deep: bool = False) -> tuple[bool | None, str | None]:
    try:
        resolved = _runtime_view(server)
        budget = _probe_budget(resolved, timeout)
        if resolved.get('command') and not resolved.get('url'):
            if not _probe_stdio(resolved):
                return False, 'command not found or not executable'
            if not deep:
                return None, None
            handshake = _stdio_handshake
        elif resolved.get('url'):
            handshake = _remote_handshake
        else:
            return False, 'server has no url or command'
        # Cleanup has its own bounded grace period in the SDK owner task.
        resolved['startup_timeout'] = budget
        await handshake(resolved)
        return True, None
    except TimeoutError:
        return False, f'startup timed out after {budget:g}s'
    except Exception as exc:
        return False, safe_mcp_error(exc)


def _probe_budget(server: dict, timeout: float) -> float:
    configured = server.get('startup_timeout')
    values = (timeout, timeout if configured is None else configured)
    if any(isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0
           for v in values):
        raise ValueError('startup_timeout must be a positive finite number')
    return min(float(v) for v in values)


def _cached_result(base: tuple, level: str, budget: float, now: float) -> ProbeResult | None:
    # A successful connection suffices regardless of its budget; a short
    # timeout failure says nothing about a request willing to wait longer.
    connections = [(key[-1], value) for key, value in _cache.items()
                   if key[:3] == base and key[3] == 'connection'
                   and value.expires_at > now
                   and (value.healthy is True or key[-1] >= budget)]
    if connections:
        return max(connections, key=lambda item: (
            item[1].healthy is True, item[0], item[1].checked_at))[1]
    if level == 'command':
        result = _cache.get((*base, 'command', 0.0))
        if result and result.expires_at > now:
            return result
    return None


def invalidate_cache() -> None:
    global _generation
    _generation += 1
    _cache.clear()


def invalidate_server(name: str, server: dict | None = None,
                      scope: str = 'global') -> None:
    # Invalidate all parameter revisions of this row, including pending writes.
    # The generation is global only as a write barrier; other cached rows stay.
    global _generation
    _generation += 1
    for key in list(_cache):
        if key[:2] == (scope, name):
            _cache.pop(key, None)


async def check_server_cached(name: str, server: dict, timeout: float = 6.0,
                              deep: bool = False, scope: str = 'global',
                              refresh: bool = False) -> ProbeResult:
    level = 'connection' if deep or (isinstance(server, dict) and server.get('url')) else 'command'
    try:
        resolved = _runtime_view(server)
        configured_budget = _probe_budget(resolved, timeout)
        base = _cache_key(name, resolved, scope)
    except Exception as exc:
        # Malformed local/SDK configuration must fail only this row. Do not
        # cache it or expose values included in validation exception text.
        completed = time.time()
        return ProbeResult(False, safe_mcp_error(exc), level,
                           completed, completed + _TTL_FAIL)
    budget = configured_budget if level == 'connection' else 0.0
    key = (*base, level, budget)
    now = time.time()
    if not refresh:
        hit = _cached_result(base, level, budget, now)
        if hit:
            return hit
    generation = _generation
    flight_key = (*key, generation)
    task = _inflight.get(flight_key)
    if task is None:
        if refresh:
            for candidate in list(_cache):
                if candidate[:3] == base:
                    _cache.pop(candidate, None)

        async def run():
            ok, reason = await check_server(resolved, configured_budget, deep=deep)
            completed = time.time()
            result = ProbeResult(ok, reason, level, completed,
                                 completed + _ttl(ok))
            if generation == _generation:
                for expired in list(_cache):
                    if _cache[expired].expires_at <= completed:
                        _cache.pop(expired, None)
                _cache[key] = result
            return result

        task = asyncio.create_task(run(), name='mcp-health')
        _inflight[flight_key] = task

        def finished(done):
            _inflight.pop(flight_key, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
    result = await asyncio.shield(task)
    # Late shallow/short failures cannot replace a successful longer probe.
    stronger = _cached_result(base, level, budget, time.time())
    if stronger:
        return stronger
    return result


async def shutdown() -> None:
    invalidate_cache()
    tasks = list(_inflight.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    _inflight.clear()
