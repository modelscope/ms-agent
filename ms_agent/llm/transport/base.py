# Copyright (c) ModelScope Contributors. All rights reserved.
"""Transport (wire-protocol) abstraction.

A ``Transport`` owns the conversion between ms-agent's internal ``Message``
representation and a provider's wire protocol, plus the API call itself. It is
constructed by ``ProviderRouter`` from a ``ProviderSpec`` and resolved
credentials.

For backward compatibility the transport returns the legacy ``Message`` /
``Generator[Message]`` (the proven hot-path contract consumed by ``LLMAgent``).
Structured ``LLMResponse`` output is available to new consumers via
``ResponseAdapter``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generator, List, Optional, Union

from ms_agent.llm.utils import Message, Tool


class Transport(ABC):

    @abstractmethod
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Tool]] = None,
        **kwargs,
    ) -> Union[Message, Generator[Message, None, None]]:
        """Run a (possibly streaming) completion.

        Returns a single ``Message`` when not streaming, or a generator of
        cumulative ``Message`` chunks when ``stream=True``.
        """
        ...

    def interrupt(self) -> None:
        """Best-effort abort of an in-flight streaming response.

        Called when the consumer abandons a stream mid-generation (e.g. the user
        hit stop) so the transport can close the underlying connection and the
        server stops producing tokens instead of running to completion into a
        dropped socket. The default is a no-op; streaming transports override
        it. Must be safe to call from a different thread than the one iterating
        the stream, and safe when nothing is in flight.
        """
        return None
