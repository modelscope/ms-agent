"""Discover available model ids from a provider's standard /models endpoint.

Best-effort only: any failure (missing key, network error, non-standard
endpoint, non-2xx) degrades silently to an empty list so the UI can fall back
to free-form manual input.
"""
from __future__ import annotations

import httpx


def _parse_ids(payload: object) -> list[str]:
    """Extract model ids from a standard OpenAI/Anthropic /models response.

    Both protocols return `{"data": [{"id": "..."}, ...]}`.
    """
    ids: list[str] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    mid = item.get("id")
                    if isinstance(mid, str) and mid:
                        ids.append(mid)
    return sorted(set(ids))


def fetch_model_ids(base_url: str, protocol: str, api_key: str) -> list[str]:
    """Return available model ids for a provider, or [] on any failure."""
    if not base_url:
        return []
    base = base_url.rstrip("/")
    try:
        if protocol == "anthropic":
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            url = f"{base}/models"
            headers = {"anthropic-version": "2023-06-01"}
            if api_key:
                headers["x-api-key"] = api_key
        else:
            url = f"{base}/models"
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        with httpx.Client(timeout=8) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code // 100 != 2:
                return []
            return _parse_ids(resp.json())
    except Exception:
        return []
