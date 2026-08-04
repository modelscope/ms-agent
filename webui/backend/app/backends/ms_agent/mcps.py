"""MCP adapter — MCPConfigManager (global + per-project) with heuristic mapping
between the WebUI's flat {transport, endpoint} and the SDK's structured server
dict ({command,args} stdio | {url,transport} remote). Ids encode scope+name;
description lives in the sidecar."""
from __future__ import annotations

import base64
import shlex
from datetime import datetime, timezone

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.schemas.mcp import Mcp, McpCreate, McpHealth, McpUpdate


def _encode_id(scope: str, name: str) -> str:
    return base64.urlsafe_b64encode(f"{scope}\x1f{name}".encode()).decode().rstrip("=")


def _decode_id(mcp_id: str) -> tuple[str, str]:
    try:
        pad = "=" * (-len(mcp_id) % 4)
        scope, name = base64.urlsafe_b64decode(mcp_id + pad).decode().split("\x1f", 1)
        return scope, name
    except Exception:
        raise NotFound("mcp not found")


def _mm_for(scope: str):
    """Return (MCPConfigManager, sdk_scope) for a WebUI scope string."""
    from ms_agent.config import MCPConfigManager

    if scope == "global":
        return MCPConfigManager(global_root=home()), "global"
    if scope.startswith("project:"):
        pid = scope.split(":", 1)[1]
        proj = pm().get(pid)
        if proj is None:
            raise BadRequest(f"unknown project: {pid}")
        return MCPConfigManager(global_root=home(), project_root=proj.path), "project"
    raise BadRequest(f"invalid scope: {scope!r}")


def _endpoint(entry: dict) -> tuple[str, str]:
    """(transport, endpoint) from a structured SDK server dict."""
    if entry.get("command"):
        parts = [entry["command"], *(entry.get("args") or [])]
        return "stdio", shlex.join(str(p) for p in parts)
    transport = entry.get("transport") or "sse"
    if transport not in ("http", "sse", "streamable_http"):
        transport = "sse"
    if transport == "streamable_http":
        transport = "http"
    return transport, entry.get("url", "")


def _server(transport: str, endpoint: str, env: dict | None = None, headers: dict | None = None) -> dict:
    if transport == "stdio":
        parts = shlex.split(endpoint)
        if not parts:
            raise BadRequest("empty stdio command")
        server = {"command": parts[0], "args": parts[1:]}
        if env:
            server["env"] = env
        return server
    server = {"url": endpoint, "transport": transport}
    if headers:
        server["headers"] = headers
    return server


def _to_schema(scope: str, name: str, entry: dict) -> Mcp:
    transport, endpoint = _endpoint(entry)
    mid = _encode_id(scope, name)
    desc = (sidecar.get("mcps", mid, {}) or {}).get("description") or entry.get("description", "")
    created = (entry.get("meta") or {}).get("added_at") or datetime.now(timezone.utc)
    return Mcp(
        id=mid,
        name=name,
        description=desc,
        transport=transport,
        endpoint=endpoint,
        enabled=entry.get("enabled", True),
        scope=scope,
        env=entry.get("env") or {},
        headers=entry.get("headers") or {},
        created_at=created,
    )


def list_mcps(scope: str | None = None) -> list[Mcp]:
    out: list[Mcp] = []
    if scope:
        mm, sdk_scope = _mm_for(scope)
        for name, entry in (mm.list(sdk_scope) or {}).items():
            out.append(_to_schema(scope, name, entry))
    else:
        from ms_agent.config import MCPConfigManager

        gm = MCPConfigManager(global_root=home())
        for name, entry in (gm.list("global") or {}).items():
            out.append(_to_schema("global", name, entry))
        for proj in pm().list():
            pmm = MCPConfigManager(global_root=home(), project_root=proj.path)
            for name, entry in (pmm.list("project") or {}).items():
                out.append(_to_schema(f"project:{proj.id}", name, entry))
    out.sort(key=lambda m: m.created_at)
    return out


def _enabled_entries() -> list[tuple[str, str, str, dict]]:
    """(id, name, scope, server_entry) for every ENABLED MCP across scopes."""
    from ms_agent.config import MCPConfigManager

    out: list[tuple[str, str, str, dict]] = []
    gm = MCPConfigManager(global_root=home())
    for name, entry in (gm.list("global") or {}).items():
        if entry.get("enabled", True):
            out.append((_encode_id("global", name), name, "global", entry))
    for proj in pm().list():
        pmm = MCPConfigManager(global_root=home(), project_root=proj.path)
        for name, entry in (pmm.list("project") or {}).items():
            if entry.get("enabled", True):
                out.append(
                    (_encode_id(f"project:{proj.id}", name), name, f"project:{proj.id}", entry)
                )
    return out


def health() -> list[McpHealth]:
    """Probe every enabled MCP (connect+initialize) and report status + reason.
    On-demand only — never call from list_mcps (each probe is a network handshake
    up to the timeout)."""
    import asyncio

    from app.backends.ms_agent import mcp_health

    entries = _enabled_entries()
    if not entries:
        return []

    async def _run():
        return await asyncio.gather(
            *(mcp_health.check_server(entry) for _, _, _, entry in entries)
        )

    results = asyncio.run(_run())
    return [
        McpHealth(id=mid, name=name, scope=scope, healthy=ok, error=err)
        for (mid, name, scope, _entry), (ok, err) in zip(entries, results)
    ]


def health_one(mcp_id: str) -> McpHealth:
    """Probe a single MCP server by id and return its health + error reason."""
    import asyncio

    from app.backends.ms_agent import mcp_health

    scope, name = _decode_id(mcp_id)
    mm, sdk_scope = _mm_for(scope)
    entry = mm.get(name, sdk_scope)
    if entry is None:
        raise NotFound("mcp not found")
    ok, err = asyncio.run(mcp_health.check_server(entry))
    return McpHealth(id=mcp_id, name=name, scope=scope, healthy=ok, error=err)


def create_mcp(body: McpCreate) -> Mcp:
    mm, sdk_scope = _mm_for(body.scope)
    if mm.get(body.name, sdk_scope) is not None:
        raise Conflict("mcp name already exists in this scope")
    server = _server(body.transport, body.endpoint, body.env, body.headers)
    server["enabled"] = body.enabled
    mm.add(body.name, server, scope=sdk_scope)
    mid = _encode_id(body.scope, body.name)
    if body.description:
        sidecar.merge("mcps", mid, {"description": body.description})
    entry = mm.get(body.name, sdk_scope) or server
    return _to_schema(body.scope, body.name, entry)


def get_mcp(mcp_id: str) -> Mcp:
    scope, name = _decode_id(mcp_id)
    mm, sdk_scope = _mm_for(scope)
    entry = mm.get(name, sdk_scope)
    if entry is None:
        raise NotFound("mcp not found")
    return _to_schema(scope, name, entry)


def update_mcp(mcp_id: str, body: McpUpdate) -> Mcp:
    scope, name = _decode_id(mcp_id)
    mm, sdk_scope = _mm_for(scope)
    cur = mm.get(name, sdk_scope)
    if cur is None:
        raise NotFound("mcp not found")

    cur_transport, cur_endpoint = _endpoint(cur)
    new_name = body.name or name
    if new_name != name and mm.get(new_name, sdk_scope) is not None:
        raise Conflict("mcp name already exists in this scope")
    transport = body.transport or cur_transport
    endpoint = body.endpoint if body.endpoint is not None else cur_endpoint
    env = body.env if body.env is not None else cur.get("env")
    headers = body.headers if body.headers is not None else cur.get("headers")
    server = _server(transport, endpoint, env, headers)
    server["enabled"] = body.enabled if body.enabled is not None else cur.get("enabled", True)

    # Clean replace (avoids stale opposite-transport keys); handles rename too.
    mm.remove(name, sdk_scope)
    mm.add(new_name, server, scope=sdk_scope)

    new_id = _encode_id(scope, new_name)
    if body.description is not None:
        sidecar.merge("mcps", new_id, {"description": body.description})
    if body.enabled is not None:
        from app.backends.ms_agent.runtime import registry

        registry.toggle_mcp(name, body.enabled)  # apply to any live session
    entry = mm.get(new_name, sdk_scope) or server
    return _to_schema(scope, new_name, entry)


def delete_mcp(mcp_id: str) -> None:
    scope, name = _decode_id(mcp_id)
    mm, sdk_scope = _mm_for(scope)
    if mm.get(name, sdk_scope) is None:
        raise NotFound("mcp not found")
    mm.remove(name, sdk_scope)  # global: delete; project: mask
    sidecar.drop("mcps", mcp_id)
    from app.backends.ms_agent.runtime import registry

    registry.toggle_mcp(name, False)  # disconnect from any live session
