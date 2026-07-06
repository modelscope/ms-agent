"""MemoryTool — bridges the unified memory system into the agent's tool system.

Delegates ALL tool schema and dispatch logic to the orchestrator (which in
turn delegates to the active MemoryBackend).  This ensures the tool
surface automatically adapts to whichever backend is configured.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase

if TYPE_CHECKING:
    from .orchestrator import MemoryOrchestrator

SERVER_NAME = "unified_memory"

MEMORY_USAGE_PROMPT = """
## Long-term Memory

You have access to a persistent long-term memory system. Use the memory tools to proactively manage it during conversation.

**When to save:**
- User explicitly states a preference (e.g. "I prefer ruff over flake8")
- User shares important project context (tech stack, conventions, deadlines)
- User corrects you — save the correction to avoid repeating the mistake
- Key decisions are made during the conversation
- User's recurring patterns you notice (coding style, communication preferences)

**When NOT to save:**
- Transient information (today's weather, one-off questions)
- Information already present in your memory
- Conversation filler or greetings
- Sensitive credentials or secrets (API keys, passwords)

**Be conservative** — only save facts that will genuinely help in future sessions. Quality over quantity.
""".strip()


class MemoryTool(ToolBase):
    """Exposes the active backend's tools to the agent's tool system.

    Tool schemas and dispatch are entirely controlled by the backend
    via ``orchestrator.get_tool_schemas()`` / ``orchestrator.handle_tool_call()``.
    """

    def __init__(self, config: Any, orchestrator: "MemoryOrchestrator") -> None:
        super().__init__(config)
        self._orch = orchestrator

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        schemas = self._orch.get_tool_schemas()
        tools: List[Tool] = []
        for s in schemas:
            tools.append(Tool(
                tool_name=s.get("tool_name", ""),
                server_name=SERVER_NAME,
                description=s.get("description", ""),
                parameters=s.get("parameters", {}),
            ))
        return {SERVER_NAME: tools} if tools else {}

    async def call_tool(
        self, server_name: str, *, tool_name: str, tool_args: dict,
    ) -> str:
        return await self._orch.handle_tool_call(tool_name, tool_args)
