"""MsAgentBackend facade — dispatches to the per-domain SDK adapters.

Domain methods are added here as each endpoint is ported. Chat is stateful and
lives in the runtime/chat modules; the facade just forwards to it.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from app.schemas.chat import ChatRequest


class MsAgentBackend:
    def chat_stream(self, req: ChatRequest) -> AsyncIterator[dict]:
        from app.backends.ms_agent import chat

        return chat.stream(req)

    def chat_attach(self, session_id: str) -> AsyncIterator[dict]:
        from app.backends.ms_agent import chat

        return chat.attach(session_id)
