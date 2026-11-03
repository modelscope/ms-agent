"""Lazy client ownership and short failure cooldown for optional decisions."""
import time

from .types import DecisionCapabilities, DecisionError


class ManagedDecisionClient:
    capabilities = DecisionCapabilities()

    def __init__(self, factory):
        self.factory = factory
        self.client = None
        self.failures = 0
        self.retry_at = 0.0

    async def decide(self, request, *, timeout=5):
        if time.monotonic() < self.retry_at:
            raise DecisionError('Decision service is cooling down')
        try:
            if self.client is None:
                self.client = self.factory()
            result = await self.client.decide(request, timeout=timeout)
            self.failures = 0
            return result
        except (DecisionError, ValueError, KeyError) as exc:
            self.failures += 1
            if self.failures >= 3:
                self.retry_at = time.monotonic() + 30
            raise DecisionError(
                str(exc) if isinstance(exc, DecisionError) else
                'Decision configuration is unavailable') from None

    async def aclose(self):
        if self.client is not None:
            client, self.client = self.client, None
            await client.aclose()
