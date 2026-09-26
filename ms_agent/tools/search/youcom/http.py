# Copyright (c) ModelScope Contributors. All rights reserved.
"""Minimal HTTP JSON client for You.com REST API (stdlib only)."""
import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class YouHTTPError(RuntimeError):
    """A You.com call that failed, with structured error fields."""

    def __init__(self,
                 message: str,
                 *,
                 status: Optional[int] = None,
                 code: str = '',
                 retry_after: Optional[int] = None,
                 detail: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.detail = detail

    @property
    def is_quota(self) -> bool:
        return self.status == 429 or 'quota' in self.code.lower()

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)


def _ssl_context():
    try:
        import certifi
        import ssl
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def get_json(
    url: str,
    params: Optional[Dict[str, str]] = None,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """GET a JSON resource."""
    if params:
        import urllib.parse
        qs = urllib.parse.urlencode(params, doseq=True)
        url = f'{url}?{qs}'
    merged = {'Accept': 'application/json'}
    merged.update(headers or {})
    req = Request(url, method='GET', headers=merged)
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
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
        detail = {}
        try:
            detail = json.loads(err_body) if err_body else {}
        except json.JSONDecodeError:
            detail = {'raw': err_body}
        code = str(detail.get('code', ''))
        msg = str(detail.get('message', '')) or str(detail.get('error', ''))
        ra = detail.get('retry_after')
        if isinstance(ra, (int, float)):
            ra = int(ra)
        else:
            try:
                ra = int(e.headers.get('retry-after')) if e.headers else None
            except (TypeError, ValueError, AttributeError):
                ra = None
        raise YouHTTPError(
            f'You.com HTTP {e.code}: {msg or detail}',
            status=e.code,
            code=code,
            retry_after=ra,
            detail=detail) from e
    except URLError as e:
        raise YouHTTPError(f'You.com network error: {e}') from e