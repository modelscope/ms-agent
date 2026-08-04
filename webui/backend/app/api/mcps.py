from fastapi import APIRouter, HTTPException

from app.core import store
from app.core.envelope import EnvelopeRoute
from app.core.settings import settings
from app.schemas.mcp import Mcp, McpCreate, McpHealth, McpUpdate

router = APIRouter(prefix="/api/mcps", tags=["mcps"], route_class=EnvelopeRoute)


def _ms() -> bool:
    return settings.agent_backend == "ms_agent"


def _validate_scope(scope: str) -> str:
    try:
        return store.scope_key(scope)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("")
def list_mcps(scope: str | None = None) -> list[Mcp]:
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.list_mcps(scope)
    rows = list(store.mcps.values())
    if scope is not None:
        normalized = _validate_scope(scope)
        rows = [m for m in rows if m["scope"] == normalized]
    rows.sort(key=lambda m: m["created_at"])
    return [Mcp.model_validate(m) for m in rows]


@router.get("/health")
def mcps_health() -> list[McpHealth]:
    """Live reachability of enabled MCP servers (on-demand connect+initialize).
    Defined before /{mcp_id} so the literal path wins over the id capture."""
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.health()
    # Mock backend has no real servers; report enabled ones as healthy.
    return [
        McpHealth(id=m["id"], name=m["name"], scope=m["scope"], healthy=True)
        for m in store.mcps.values()
        if m.get("enabled", True)
    ]


@router.get("/{mcp_id}/health")
def mcp_health_check(mcp_id: str) -> McpHealth:
    """Probe a single MCP server's connectivity. Returns healthy + error reason."""
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.health_one(mcp_id)
    row = store.mcps.get(mcp_id)
    if not row:
        raise HTTPException(404, "mcp not found")
    return McpHealth(
        id=mcp_id, name=row["name"], scope=row["scope"], healthy=True
    )


@router.post("", status_code=201)
def create_mcp(body: McpCreate) -> Mcp:
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.create_mcp(body)
    scope = _validate_scope(body.scope)
    mid = store.new_id("m-")
    row = {
        "id": mid,
        "name": body.name,
        "description": body.description,
        "transport": body.transport,
        "endpoint": body.endpoint,
        "enabled": body.enabled,
        "scope": scope,
        "created_at": store.now(),
    }
    store.mcps[mid] = row
    return Mcp.model_validate(row)


@router.get("/{mcp_id}")
def get_mcp(mcp_id: str) -> Mcp:
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.get_mcp(mcp_id)
    row = store.mcps.get(mcp_id)
    if not row:
        raise HTTPException(404, "mcp not found")
    return Mcp.model_validate(row)


@router.patch("/{mcp_id}")
def update_mcp(mcp_id: str, body: McpUpdate) -> Mcp:
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.update_mcp(mcp_id, body)
    row = store.mcps.get(mcp_id)
    if not row:
        raise HTTPException(404, "mcp not found")
    for field in ("name", "description", "transport", "endpoint", "enabled"):
        value = getattr(body, field)
        if value is not None:
            row[field] = value
    return Mcp.model_validate(row)


@router.delete("/{mcp_id}", status_code=204)
def delete_mcp(mcp_id: str) -> None:
    if _ms():
        from app.backends.ms_agent import mcps

        return mcps.delete_mcp(mcp_id)
    if mcp_id not in store.mcps:
        raise HTTPException(404, "mcp not found")
    del store.mcps[mcp_id]
