"""MCP adapter — MCPConfigManager (global + per-project) with heuristic mapping
between the WebUI's flat {transport, endpoint} and the SDK's structured server
dict ({command,args} stdio | {url,transport} remote). Ids encode scope+name;
description lives in the sidecar."""
from __future__ import annotations

import base64
import json
import shlex
from datetime import datetime, timezone

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent import sidecar
from app.backends.ms_agent.common import home, pm
from app.backends.ms_agent.settings_store import settings_lock
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


def _is_tombstone(entry: dict) -> bool:
    """True for a project entry that only MASKS a server instead of defining one.

    `MCPConfigManager.remove(scope='project')` writes
    `{enabled: false, _removed: true}`; normalization then strips `_removed` and
    leaves an entry with no endpoint at all. Such a row is not a server — listing
    it is what made a removed project MCP look merely disabled.
    """
    if entry.get("_removed"):
        return True
    return not entry.get("url") and not entry.get("command")


def list_mcps(scope: str | None = None) -> list[Mcp]:
    out: list[Mcp] = []
    if scope:
        mm, sdk_scope = _mm_for(scope)
        for name, entry in (mm.list(sdk_scope) or {}).items():
            if _is_tombstone(entry):
                continue
            out.append(_to_schema(scope, name, entry))
    else:
        from ms_agent.config import MCPConfigManager

        gm = MCPConfigManager(global_root=home())
        for name, entry in (gm.list("global") or {}).items():
            out.append(_to_schema("global", name, entry))
        for proj in pm().list():
            pmm = MCPConfigManager(global_root=home(), project_root=proj.path)
            for name, entry in (pmm.list("project") or {}).items():
                if _is_tombstone(entry):
                    continue
                out.append(_to_schema(f"project:{proj.id}", name, entry))
    # NO re-sorting: the order IS the order of mcp.json, which is what the user
    # controls by editing/reordering that file. Sorting by created_at made the
    # list depend on a timestamp the SDK rewrites on edit, so toggling a server
    # moved its card; it also meant a manual reorder in the JSON had no effect.
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
    # Locked: every mutation here is a read-modify-write of the whole mcp file,
    # and the SDK manager's own lock is per INSTANCE (a fresh one per request),
    # so two threadpooled requests would otherwise load the same old file and
    # each save its own partial view — silently resurrecting the other's changes.
    with settings_lock():
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
    with settings_lock():  # see create_mcp: guards the read-modify-write
        return _update_mcp_locked(mcp_id, body)


def _update_mcp_locked(mcp_id: str, body: McpUpdate) -> Mcp:
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
    enabled = body.enabled if body.enabled is not None else cur.get("enabled", True)

    if new_name == name and transport == cur_transport:
        # In-place merge: it keeps the entry where it sits in mcp.json and keeps
        # its original meta.added_at. The remove+add below moves the key to the
        # END of the file and lets the SDK restamp added_at — which is why simply
        # toggling a server used to reshuffle the list.
        patch = _server(transport, endpoint, env, headers)
        patch["enabled"] = enabled
        # A merge cannot drop keys, so clearing env/headers has to be explicit.
        if body.env is not None and not env:
            patch["env"] = {}
        if body.headers is not None and not headers:
            patch["headers"] = {}
        mm.update(name, patch, scope=sdk_scope)
    else:
        # Rename or transport switch: the entry's shape changes, so it is replaced
        # wholesale — merging would leave the previous transport's keys behind
        # (a stale `url` after switching to stdio). `meta` is carried over so
        # added_at still says when the server was ADDED.
        server = _server(transport, endpoint, env, headers)
        server["enabled"] = enabled
        if cur.get("meta"):
            server["meta"] = cur["meta"]
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


def _project_owned(name: str) -> bool:
    """True when `name` is defined by the PROJECT itself rather than inherited
    from the global scope."""
    from ms_agent.config import MCPConfigManager

    gm = MCPConfigManager(global_root=home())
    return gm.get(name, "global") is None


def _hard_remove_project_entry(mm, name: str) -> None:
    """Delete a project-owned server from the project's mcp.json.

    The SDK's `remove(scope='project')` always writes a MASK
    (`{enabled: false, _removed: true}`) because a project may hide a global
    server without deleting the global definition. For a server the project owns
    there is nothing to hide, so masking made "remove" behave like "disable" —
    the card stayed, just switched off. No SDK call can delete a project key, so
    the file is edited directly (same shape/formatting the SDK writes).
    """
    path = mm.project_mcp_path
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        return
    del servers[name]
    data["mcpServers"] = servers
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def replace_mcps(scope: str, bodies: list[McpCreate]) -> list[Mcp]:
    """Make `scope` contain exactly `bodies`, in this order.

    For the raw-JSON editor the document IS the desired state, so this is one
    atomic operation instead of the client deleting every server and re-creating
    them one by one — which lost data whenever a later create was rejected (the
    deletes had already landed), and could not survive two overlapping requests.

    Everything is validated BEFORE the first write, `meta` is carried over for
    names that already existed (so `added_at` keeps meaning "added at"), and the
    write order is the caller's order, which is what makes reordering the JSON
    reorder the list.
    """
    with settings_lock():
        mm, sdk_scope = _mm_for(scope)
        current = mm.list(sdk_scope) or {}

        seen: set[str] = set()
        built: list[tuple[str, dict, str | None]] = []
        for body in bodies:
            if body.name in seen:
                raise Conflict(f"duplicate mcp name: {body.name}")
            seen.add(body.name)
            server = _server(body.transport, body.endpoint, body.env, body.headers)
            server["enabled"] = body.enabled
            meta = (current.get(body.name) or {}).get("meta")
            if meta:
                server["meta"] = meta
            built.append((body.name, server, body.description))

        # Nothing above touched disk, so a rejected payload leaves the scope as it
        # was. From here on the writes are inside the lock, hence atomic to any
        # other request.
        for name in list(current):
            if sdk_scope == "project":
                _hard_remove_project_entry(mm, name)
            else:
                mm.remove(name, sdk_scope)
        for name, server, description in built:
            mm.add(name, server, scope=sdk_scope)
            mid = _encode_id(scope, name)
            if description:
                sidecar.merge("mcps", mid, {"description": description})

        # Drop sidecar rows of servers that are gone for good.
        for name in current:
            if name not in seen:
                sidecar.drop("mcps", _encode_id(scope, name))

    return list_mcps(scope)


def delete_mcp(mcp_id: str) -> None:
    with settings_lock():  # see create_mcp: guards the read-modify-write
        _delete_mcp_locked(mcp_id)


def _delete_mcp_locked(mcp_id: str) -> None:
    scope, name = _decode_id(mcp_id)
    mm, sdk_scope = _mm_for(scope)
    if mm.get(name, sdk_scope) is None:
        raise NotFound("mcp not found")
    if sdk_scope == "project" and _project_owned(name):
        _hard_remove_project_entry(mm, name)
    else:
        # Global: real delete. Project entry shadowing a GLOBAL server: mask it,
        # so the server stays defined globally but is off for this project.
        mm.remove(name, sdk_scope)
    sidecar.drop("mcps", mcp_id)
    from app.backends.ms_agent.runtime import registry

    registry.toggle_mcp(name, False)  # disconnect from any live session
