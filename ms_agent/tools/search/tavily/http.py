# Copyright (c) ModelScope Contributors. All rights reserved.
"""Minimal HTTP JSON client for Tavily REST API (stdlib only)."""
import json
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(
    url: str,
    body: Dict[str, Any],
    *,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """
    POST JSON and parse JSON response.

    Raises:
        RuntimeError: on HTTP errors or invalid JSON (includes Tavily error body).
    """
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = Request(
        url,
        data=data,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
            if not raw.strip():
                return {}
            return json.loads(raw)
    except HTTPError as e:
        err_body = ''
        try:
            err_body = e.read().decode('utf-8', errors='replace')
        except Exception:
            pass
        try:
            detail = json.loads(err_body) if err_body else {}
        except json.JSONDecodeError:
            detail = {'raw': err_body}
        raise RuntimeError(
            f'Tavily HTTP {e.code}: {detail}') from e
    except URLError as e:
        raise RuntimeError(f'Tavily network error: {e}') from e
