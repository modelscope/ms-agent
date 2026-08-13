"""MemoryTool — bridges the unified memory system into the agent's tool system.

Delegates ALL tool schema and dispatch logic to the orchestrator (which in
turn delegates to the active MemoryBackend).  This ensures the tool
surface automatically adapts to whichever backend is configured.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase

if TYPE_CHECKING:
    from .orchestrator import MemoryOrchestrator

from ms_agent.prompting.builtin import MEMORY_TOOL_GUIDANCE

SERVER_NAME = 'unified_memory'

#: Deprecated alias — the guidance text now lives in prompting.builtin and is
#: injected as an assembly segment by LLMAgent (never by mutating config).
MEMORY_USAGE_PROMPT = MEMORY_TOOL_GUIDANCE


class MemoryTool(ToolBase):
    """Exposes the active backend's tools to the agent's tool system.

    Tool schemas and dispatch are entirely controlled by the backend
    via ``orchestrator.get_tool_schemas()`` / ``orchestrator.handle_tool_call()``.
    """

    def __init__(self, config: Any,
                 orchestrator: 'MemoryOrchestrator') -> None:
        super().__init__(config)
        self._orch = orchestrator

    async def connect(self) -> None:
        pass

    async def _get_tools_inner(self) -> Dict[str, Any]:
        schemas = self._orch.get_tool_schemas()
        tools: List[Tool] = []
        for s in schemas:
            tools.append(
                Tool(
                    tool_name=s.get('tool_name', ''),
                    server_name=SERVER_NAME,
                    description=s.get('description', ''),
                    parameters=s.get('parameters', {}),
                ))
        return {SERVER_NAME: tools} if tools else {}

    async def call_tool(
        self,
        server_name: str,
        *,
        tool_name: str,
        tool_args: dict,
    ) -> str:
        return await self._orch.handle_tool_call(tool_name, tool_args)
