"""Async MCP health probe.

A remote MCP whose host is reachable but whose endpoint is stale/invalid (e.g.
"Session terminated") still breaks a chat turn: the agent's connect raises and
aborts the run. A TCP check can't catch that — only a real MCP handshake can.

This probes each enabled server (connect + initialize) with a timeout, fully
isolated in its own task so a failure/hang/anyio-teardown can't touch the chat,
and returns only the servers that initialized. Runs once per session build.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil

logger = logging.getLogger("app.ms_agent.mcp_health")


async def _remote_handshake(server: dict) -> bool:
    """connect + initialize a remote MCP, entered/exited within THIS task so an
    anyio cross-task teardown can't leak. Raises on failure."""
    url = server["url"]
    transport = str(server.get("transport") or "").lower()
    headers = server.get("headers") or None
    from mcp import ClientSession

    if transport == "sse":
        from mcp.client.sse import sse_client as connect
    else:  # http / streamable_http
        from mcp.client.streamable_http import streamablehttp_client as connect
    async with connect(url, headers=headers) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
    return True


async def _probe_remote(server: dict, timeout: float) -> bool:
    if not server.get("url"):
        return False
    try:
        return bool(await asyncio.wait_for(_remote_handshake(server), timeout))
    except Exception:
        return False


def _short_error(exc: BaseException) -> str:
    """Unwrap anyio ExceptionGroups to a short, human-readable reason."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    msg = str(exc).strip() or type(exc).__name__
    return msg[:200]


def _runtime_view(server: dict) -> dict:
    """The server entry as the runtime will actually use it: ${VAR}
    placeholders resolved from the process environment. Management surfaces
    keep the placeholder form; probing with it would 401 against a healthy
    server. Idempotent on already-expanded entries."""
    from ms_agent.tui.managed_config import expand_env_placeholders

    return expand_env_placeholders(server)


async def check_server(server: dict, timeout: float = 6.0) -> tuple[bool, str | None]:
    """Probe one server and return (healthy, error_reason). Same handshake as the
    build-time filter, but surfaces WHY an enabled server was dropped."""
    server = _runtime_view(server)
    if server.get("command"):
        ok = _probe_stdio(server)
        return ok, (None if ok else "command not found on PATH")
    if not server.get("url"):
        return False, "server has no url or command"
    try:
        await asyncio.wait_for(_remote_handshake(server), timeout)
        return True, None
    except asyncio.TimeoutError:
        return False, f"timed out after {int(timeout)}s"
    except Exception as exc:  # noqa: BLE001 — report the reason, don't raise
        return False, _short_error(exc)


def _probe_stdio(server: dict) -> bool:
    command = server.get("command")
    if not command:
        return True
    return bool(shutil.which(command)) or os.path.isfile(command)


async def filter_healthy(servers: dict, timeout: float = 6.0) -> dict:
    """Return the subset of servers that pass their probe (concurrently)."""
    if not servers:
        return {}

    async def _check(name: str, server: dict) -> tuple[str, bool]:
        server = _runtime_view(server)
        if server.get("command"):
            return name, _probe_stdio(server)
        return name, await _probe_remote(server, timeout)

    results = await asyncio.gather(*(_check(n, s) for n, s in servers.items()))
    healthy = {name: servers[name] for name, ok in results if ok}
    dropped = [name for name, ok in results if not ok]
    if dropped:
        logger.warning("dropping unhealthy MCP server(s): %s", ", ".join(sorted(dropped)))
    return healthy
