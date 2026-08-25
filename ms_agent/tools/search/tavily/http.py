# Copyright (c) ModelScope Contributors. All rights reserved.
"""Minimal HTTP JSON client for Tavily REST API (stdlib only)."""
import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TavilyHTTPError(RuntimeError):
    """A Tavily call that failed, with the pieces a caller can act on.

    Plain ``RuntimeError`` forced every caller to re-parse the message to tell
    "you are out of quota, ask the user for a key" from "that host is down".
    Keyless mode makes that distinction routine rather than exceptional — the
    free tier is a small hourly bucket — so the parts travel as fields:
    ``status`` (HTTP code, None for transport failures), ``code`` (Tavily's own
    machine-readable ``error.code``, e.g. ``hourly_cap_reached``) and
    ``retry_after`` seconds when the response carried one.
    """

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
        """Out of quota — retryable later, and fixable now with an API key."""
        return self.status == 429 or self.code in ('hourly_cap_reached',
                                                   'rate_limit_exceeded')

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)


def _ssl_context():
    """A verifying TLS context that works on interpreters with no CA store.

    ``urlopen`` uses the interpreter's default store, which is empty in some
    virtualenvs (``ssl.get_default_verify_paths().cafile is None`` — measured on
    the WebUI backend's venv, where every Tavily call died with
    CERTIFICATE_VERIFY_FAILED). certifi is already an indirect dependency there;
    when it is missing we hand back None so urlopen behaves exactly as before.
    Never disables verification.
    """
    try:
        import certifi
        import ssl
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _parse_error_body(raw: str) -> Any:
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {'raw': raw}


def _dig_error(detail: Any) -> tuple:
    """``(code, message, retry_after)`` out of Tavily's error envelope.

    Two shapes are in the wild: ``{"error": {"code", "message",
    "retry_after_seconds"}}`` (keyless quota) and ``{"detail": {"error": ...}}``
    (auth). Anything else degrades to empty strings rather than raising while
    already handling an error.
    """
    code = message = ''
    retry_after = None
    node = detail
    if isinstance(node, dict) and isinstance(node.get('detail'), dict):
        node = node['detail']
    if isinstance(node, dict):
        err = node.get('error')
        if isinstance(err, dict):
            code = str(err.get('code') or '')
            message = str(err.get('message') or '')
            ra = err.get('retry_after_seconds')
            if isinstance(ra, (int, float)):
                retry_after = int(ra)
        elif isinstance(err, str):
            message = err
    return code, message, retry_after


def post_json(
    url: str,
    body: Dict[str, Any],
    *,
    timeout: float = 120.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    POST JSON and parse JSON response.

    ``headers`` is merged over the defaults — that is how keyless mode is
    selected (``X-Tavily-Access-Mode: keyless``).

    Raises:
        TavilyHTTPError: on HTTP errors or invalid JSON (carries Tavily's own
            error code / retry-after so callers can tell quota from outage).
    """
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    merged = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    merged.update(headers or {})
    req = Request(url, data=data, method='POST', headers=merged)
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
        detail = _parse_error_body(err_body)
        code, message, retry_after = _dig_error(detail)
        if retry_after is None:
            header_value = None
            try:
                header_value = e.headers.get('retry-after')
            except Exception:
                pass
            if header_value:
                try:
                    retry_after = int(float(header_value))
                except (TypeError, ValueError):
                    retry_after = None
        raise TavilyHTTPError(
            f'Tavily HTTP {e.code}: {message or detail}',
            status=e.code,
            code=code,
            retry_after=retry_after,
            detail=detail) from e
    except URLError as e:
        raise TavilyHTTPError(f'Tavily network error: {e}') from e
