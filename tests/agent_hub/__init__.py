# Copyright (c) Alibaba, Inc. and its affiliates.
# Copyright (c) Alibaba, Inc. and its affiliates.
"""Shared helpers for agent tests."""


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
