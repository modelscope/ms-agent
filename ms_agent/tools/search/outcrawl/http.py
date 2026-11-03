# Copyright (c) ModelScope Contributors. All rights reserved.
"""Minimal HTTP JSON client for the Outcrawl REST API (stdlib only)."""
import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OUTCRAWL_API_BASE = 'https://api.outcrawl.ai/v1'


class OutcrawlHTTPError(RuntimeError):
    """An Outcrawl call that failed, with the fields a caller can act on.

    ``status`` is the HTTP code (None for transport failures), ``code`` is
    Outcrawl's machine-readable ``code`` (e.g. ``unauthorized``) and
    ``retry_after`` is set when the response carried a Retry-After header.
    The ``is_quota`` / ``is_auth`` properties match the ones
    ``WebSearchTool._search_error_payload`` reads.
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
        """Rate limited or out of credits."""
        return self.status in (402, 429)

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)


def _ssl_context():
    """A verifying TLS context backed by certifi when it is installed."""
    try:
        import certifi
        import ssl
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def post_json(path: str,
              body: Dict[str, Any],
              *,
              api_key: str,
              timeout: float = 60.0) -> Dict[str, Any]:
    """
    POST JSON to ``OUTCRAWL_API_BASE + path`` and parse the JSON response.

    Raises:
        OutcrawlHTTPError: on HTTP errors, network errors or invalid JSON.
    """
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    req = Request(
        f'{OUTCRAWL_API_BASE}{path}',
        data=data,
        method='POST',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            # The default Python-urllib agent is refused at the API edge.
            'User-Agent': 'ms-agent',
        })
    try:
        with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
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
        code, message = '', ''
        if isinstance(detail, dict):
            code = str(detail.get('code') or '')
            message = str(detail.get('message') or '')
        retry_after = None
        try:
            header_value = e.headers.get('retry-after')
            if header_value:
                retry_after = int(float(header_value))
        except (AttributeError, TypeError, ValueError):
            retry_after = None
        raise OutcrawlHTTPError(
            f'Outcrawl HTTP {e.code}: {message or detail}',
            status=e.code,
            code=code,
            retry_after=retry_after,
            detail=detail) from e
    except URLError as e:
        raise OutcrawlHTTPError(f'Outcrawl network error: {e}') from e

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OutcrawlHTTPError(
            f'Outcrawl returned invalid JSON: {raw[:200]}') from e
