"""MCP list ordering and project-scope removal.

Two behaviours users depend on and that regressed once already:

* The order shown is the order of ``mcp.json``. Editing a server (toggling it
  most of all) must not move its card; only reordering that file may.
* "Remove" on a project-owned server deletes it. The SDK's project-scope
  ``remove`` only writes a mask (``{enabled: false, _removed: true}``), which
  made removal look like a mere disable — the card stayed, switched off.
"""
import json

import pytest

from app.backends.errors import BadRequest
from app.backends.ms_agent import mcps
from app.backends.ms_agent import projects as P
from app.schemas.mcp import McpCreate, McpUpdate
from app.schemas.project import ProjectCreate


@pytest.fixture
def two_global_mcps():
    first = mcps.create_mcp(
        McpCreate(name="order-first", transport="sse",
                  endpoint="https://example.com/a/sse", scope="global")
    )
    second = mcps.create_mcp(
        McpCreate(name="order-second", transport="sse",
                  endpoint="https://example.com/b/sse", scope="global")
    )
    yield first, second
    for m in (first, second):
        try:
            mcps.delete_mcp(m.id)
        except Exception:
            pass


@pytest.fixture
def project():
    proj = P.create_project(ProjectCreate(name="mcp-scope-test"))
    yield proj
    P.delete_project(proj.id)


def _names(scope="global"):
    return [m.name for m in mcps.list_mcps(scope)]


def test_toggling_keeps_list_order_and_added_at(two_global_mcps):
    first, second = two_global_mcps
    before = _names()
    assert before.index("order-first") < before.index("order-second")
    added_at = {m.name: m.created_at for m in mcps.list_mcps("global")}

    # Toggle the FIRST one: the case that used to send it to the end, because the
    # update was a remove+add (re-appending the key and restamping added_at)
    # while the list was sorted by that timestamp.
    mcps.update_mcp(first.id, McpUpdate(enabled=False))
    assert _names() == before
    mcps.update_mcp(first.id, McpUpdate(enabled=True))
    mcps.update_mcp(second.id, McpUpdate(enabled=False))
    mcps.update_mcp(second.id, McpUpdate(enabled=True))
    assert _names() == before

    after = {m.name: m.created_at for m in mcps.list_mcps("global")}
    assert after == added_at


def test_editing_endpoint_keeps_position(two_global_mcps):
    first, _ = two_global_mcps
    before = _names()
    updated = mcps.update_mcp(
        first.id, McpUpdate(endpoint="https://example.com/moved/sse")
    )
    assert updated.endpoint == "https://example.com/moved/sse"
    assert _names() == before


def test_removing_project_mcp_deletes_it(project):
    scope = f"project:{project.id}"
    created = mcps.create_mcp(
        McpCreate(name="proj-tool", transport="sse",
                  endpoint="https://example.com/p/sse", scope=scope)
    )
    assert _names(scope) == ["proj-tool"]

    mcps.delete_mcp(created.id)

    # Gone from the listing AND from disk — not left behind as a disabled row.
    assert _names(scope) == []
    path = mcps._mm_for(scope)[0].project_mcp_path
    on_disk = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
    assert "proj-tool" not in on_disk


def test_mask_rows_are_not_listed(project):
    """A row that defines no server (the SDK's removal mask) is not a card."""
    scope = f"project:{project.id}"
    mm, sdk_scope = mcps._mm_for(scope)
    mm.add("masked", {"enabled": False, "_removed": True}, scope=sdk_scope)

    assert "masked" not in _names(scope)


def _replace(scope, *specs):
    return mcps.replace_mcps(
        scope,
        [
            McpCreate(name=n, transport="sse",
                      endpoint=f"https://example.com/{n}/sse", scope=scope)
            for n in specs
        ],
    )


def test_replace_renames_instead_of_duplicating(project):
    """The raw-JSON editor's document is the desired state: a renamed key renames
    that server rather than adding a second one beside it."""
    scope = f"project:{project.id}"
    _replace(scope, "keep-me", "rename-me")
    assert _names(scope) == ["keep-me", "rename-me"]

    _replace(scope, "keep-me", "renamed")

    assert _names(scope) == ["keep-me", "renamed"]


def test_replace_follows_document_order(project):
    scope = f"project:{project.id}"
    _replace(scope, "a", "b", "c")
    assert _names(scope) == ["a", "b", "c"]

    _replace(scope, "c", "a", "b")
    assert _names(scope) == ["c", "a", "b"]


def test_replace_rejects_bad_payload_without_touching_anything(project):
    """Validation happens before the first write — the old client deleted every
    server first, so one rejected entry emptied the whole scope."""
    scope = f"project:{project.id}"
    _replace(scope, "survivor-1", "survivor-2")
    before = _names(scope)

    with pytest.raises(BadRequest):
        mcps.replace_mcps(
            scope,
            [
                McpCreate(name="survivor-1", transport="sse",
                          endpoint="https://example.com/1/sse", scope=scope),
                McpCreate(name="broken", transport="stdio",
                          endpoint="   ", scope=scope),
            ],
        )

    assert _names(scope) == before


def test_replace_keeps_added_at_of_surviving_servers(project):
    scope = f"project:{project.id}"
    _replace(scope, "old-timer")
    added_at = {m.name: m.created_at for m in mcps.list_mcps(scope)}

    _replace(scope, "old-timer", "newcomer")

    after = {m.name: m.created_at for m in mcps.list_mcps(scope)}
    assert after["old-timer"] == added_at["old-timer"]
