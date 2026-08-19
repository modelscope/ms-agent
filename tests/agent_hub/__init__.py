# Copyright (c) Alibaba, Inc. and its affiliates.
# Copyright (c) Alibaba, Inc. and its affiliates.
"""Shared helpers for agent tests."""
import unittest


def skip_if_server_rejects(*frameworks):
    """Skip the current test when the server will not create repos for *frameworks*.

    Repo creation is gated server-side to the same set the CLI exposes by
    default; anything else comes back as ``invalid framework, must be one of:
    ms-agent, qwenpaw`` and no repo is created, so the test would go on to fail
    on an unrelated 404 ("project not found") that says nothing about the real
    cause. ``TRY_EXP_FRAMEWORKS`` only lifts the client-side gate, never this
    one, so these cases cannot pass online no matter how they are configured.

    The gated frameworks stay fully covered offline, and these skips disappear
    on their own once the server accepts more frameworks.
    """
    from ms_agent.agent_hub._commands import STABLE_FRAMEWORKS
    rejected = sorted(set(frameworks) - set(STABLE_FRAMEWORKS))
    if rejected:
        raise unittest.SkipTest(
            f"server only creates agent repos for "
            f"{', '.join(sorted(STABLE_FRAMEWORKS))}; "
            f"cannot exercise {', '.join(rejected)} online")


def delete_matching_repos(client, owner, substrings, *, page_size=100, max_pages=50):
    """Best-effort: delete every remote agent repo under *owner* whose name
    contains any of *substrings*.

    Online test classes call this in ``setUpClass`` to start from a clean slate,
    so leftover or half-created repos from earlier runs cannot mask or break a
    fresh run. All test repos are disposable, hence every failure is swallowed.
    """
    if not owner or client is None:
        return
    matched: list[str] = []
    try:
        page = 1
        seen: set[str] = set()
        while page <= max_pages:
            resp = client.list_agents(owner=owner, page_number=page, page_size=page_size)
            items = (resp or {}).get("items") or []
            if not items:
                break
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = (
                    it.get("name")
                    or it.get("Name")
                    or (it.get("id") or it.get("Id") or "").split("/")[-1]
                )
                if not name or name in seen:
                    continue
                seen.add(name)
                if any(s in name for s in substrings):
                    matched.append(name)
            if len(items) < page_size:
                break
            page += 1
    except Exception:
        return
    for name in matched:
        try:
            client.delete_repo(owner, name)
        except Exception:
            pass
# Copyright (c) Alibaba, Inc. and its affiliates.
