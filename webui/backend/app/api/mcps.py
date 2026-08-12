from fastapi import APIRouter, HTTPException

from app.core.envelope import EnvelopeRoute
from app.schemas.mcp import Mcp, McpCreate, McpHealth, McpReplace, McpUpdate

router = APIRouter(prefix="/api/mcps", tags=["mcps"], route_class=EnvelopeRoute)


@router.get("")
def list_mcps(scope: str | None = None) -> list[Mcp]:
    from app.backends.ms_agent import mcps

    return mcps.list_mcps(scope)


@router.get("/health")
def mcps_health() -> list[McpHealth]:
    """Live reachability of enabled MCP servers (on-demand connect+initialize).
    Defined before /{mcp_id} so the literal path wins over the id capture."""
    from app.backends.ms_agent import mcps

    return mcps.health()


@router.get("/{mcp_id}/health")
def mcp_health_check(mcp_id: str) -> McpHealth:
    """Probe a single MCP server's connectivity. Returns healthy + error reason."""
    from app.backends.ms_agent import mcps

    return mcps.health_one(mcp_id)


@router.put("")
def replace_mcps(body: McpReplace) -> list[Mcp]:
    """Replace one scope's servers with exactly `body.servers`, in that order.

    The raw-JSON editor saves a whole document, so it needs one atomic call: the
    per-item delete+create dance it used before could half-apply.
    """
    from app.backends.ms_agent import mcps

    return mcps.replace_mcps(body.scope, body.servers)


@router.post("", status_code=201)
def create_mcp(body: McpCreate) -> Mcp:
    from app.backends.ms_agent import mcps

    return mcps.create_mcp(body)


@router.get("/{mcp_id}")
def get_mcp(mcp_id: str) -> Mcp:
    from app.backends.ms_agent import mcps

    return mcps.get_mcp(mcp_id)


@router.patch("/{mcp_id}")
def update_mcp(mcp_id: str, body: McpUpdate) -> Mcp:
    from app.backends.ms_agent import mcps

    return mcps.update_mcp(mcp_id, body)


@router.delete("/{mcp_id}", status_code=204)
def delete_mcp(mcp_id: str) -> None:
    from app.backends.ms_agent import mcps

    return mcps.delete_mcp(mcp_id)
