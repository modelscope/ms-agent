"""System One transport. No chat emulation, redirects, or implicit retries."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

from .types import (DecisionCapabilities, DecisionError, DecisionRequest,
                    DecisionResponse)


class SystemOneClient:
    capabilities = DecisionCapabilities()

    def __init__(self,
                 *,
                 base_url: str,
                 api_key: str,
                 model: str,
                 transport=None):
        import httpx
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment):
            raise DecisionError('Invalid decision endpoint')
        if not api_key or not model:
            raise DecisionError('Decision model credentials are missing')
        base = base_url.rstrip('/')
        self._url = base if base.endswith(
            '/systemone') else base + '/systemone'
        self._model = model
        self._http = httpx.AsyncClient(
            headers={'Authorization': 'Bearer ' + api_key},
            follow_redirects=False,
            timeout=5,
            transport=transport)

    async def decide(self,
                     request: DecisionRequest,
                     *,
                     timeout: float = 5) -> DecisionResponse:
        import httpx
        request.validate(self.capabilities)
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(
                self._http.post(
                    self._url,
                    json={
                        'model': self._model,
                        'state': request.state,
                        'questions': request.questions
                    },
                    timeout=timeout), timeout)
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise DecisionError('Decision response is too large')
            return DecisionResponse.parse(
                response.text,
                request,
                elapsed_ms=(time.monotonic() - started) * 1000)
        except (TimeoutError, httpx.TimeoutException):
            raise DecisionError('Decision request timed out') from None
        except httpx.HTTPStatusError as exc:
            raise DecisionError(
                f'Decision service returned HTTP {exc.response.status_code}'
            ) from None
        except httpx.RequestError:
            raise DecisionError('Decision service is unavailable') from None

    async def aclose(self):
        await self._http.aclose()
