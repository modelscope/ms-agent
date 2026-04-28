# Copyright (c) ModelScope Contributors. All rights reserved.
import logging
from typing import Any, Awaitable, Callable

from ms_agent.capabilities.descriptor import CapabilityDescriptor

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[dict[str, Any]]]


class CapabilityRegistry:
    """Central registry that maps capability descriptors to their handler functions.

    Capabilities are registered at three granularities (project / component / tool)
    and can be discovered by name, tag, or granularity.  ``invoke()`` dispatches to
    the handler, wrapping ms-agent internals behind a uniform async interface.
    """

    def __init__(self) -> None:
        self._descriptors: dict[str, CapabilityDescriptor] = {}
        self._handlers: dict[str, Handler] = {}

    def register(self, descriptor: CapabilityDescriptor, handler: Handler) -> None:
        if descriptor.name in self._descriptors:
            logger.warning('Overwriting capability %s', descriptor.name)
        self._descriptors[descriptor.name] = descriptor
        self._handlers[descriptor.name] = handler

    def list_all(self) -> list[CapabilityDescriptor]:
        return list(self._descriptors.values())

    def get(self, name: str) -> CapabilityDescriptor | None:
        return self._descriptors.get(name)

    def discover(
        self,
        *,
        granularity: str | list[str] | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
    ) -> list[CapabilityDescriptor]:
        """Filter capabilities by granularity, tags, or free-text query."""
        results = self.list_all()

        if granularity is not None:
            levels = [granularity] if isinstance(granularity, str) else granularity
            results = [c for c in results if c.granularity in levels]

        if tags:
            tag_set = set(tags)
            results = [c for c in results if tag_set & set(c.tags)]

        if query:
            q = query.lower()
            results = [
                c for c in results if q in c.name.lower() or q in c.summary.lower() or q in c.description.lower()
            ]

        return results

    async def invoke(self, name: str, args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Invoke a registered capability by name."""
        if name not in self._handlers:
            return {'error': f'Unknown capability: {name}'}
        handler = self._handlers[name]
        try:
            return await handler(args, **kwargs)
        except Exception as e:
            logger.exception('Capability %s failed', name)
            return {'error': str(e)}
