"""ToolBasedExtractor — uses ``save_memory`` tool with forced tool_choice
to ask the LLM to consolidate conversation into a MEMORY.md update.

The LLM is given the current MEMORY.md content plus the conversation
fragment and must output a ``memory_update`` string that fully replaces
the file.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import MemoryEntry

logger = get_logger()

SAVE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": "保存整合结果到持久化存储。输出完整的长期记忆 markdown。",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_update": {
                    "type": "string",
                    "description": (
                        "完整的长期记忆 markdown，包含所有现有事实加新增内容。"
                        "无变化则原样返回。"
                    ),
                }
            },
            "required": ["memory_update"],
        },
    },
}

CONSOLIDATION_SYSTEM_PROMPT = """\
You are a memory consolidation assistant. Your task is to review the \
conversation and update the agent's long-term memory document.

Current MEMORY.md:
---
{current_memory}
---

Instructions:
1. Merge new information from the conversation into the memory document.
2. Keep important facts: user preferences, project context, key decisions, \
corrections.
3. Remove outdated or contradicted information.
4. Use concise Markdown with sections (## headers + bullet lists).
5. The output must be COMPLETE — it will fully replace the current MEMORY.md.
6. Preserve the existing structure but reorganize if needed.
7. Stay within ~{char_limit} characters.
8. Call the save_memory tool with the updated content."""

FLUSH_SYSTEM_PROMPT = """\
The conversation is about to be compressed. Important information from \
older messages will be lost. Review the conversation below and save any \
noteworthy facts to long-term memory — prioritize user preferences, \
corrections, and repeated patterns.

Current MEMORY.md:
---
{current_memory}
---

Call save_memory with the updated memory content."""


class ToolBasedExtractor:
    """Phase 1 extractor: LLM + forced tool call → MEMORY.md full replace."""

    def __init__(self, config: MemoryConfig, llm=None):
        self.config = config
        self.llm = llm

    def set_llm(self, llm) -> None:
        self.llm = llm

    async def extract(
        self, messages: List[Dict[str, Any]],
        current_memory: str = "",
        is_flush: bool = False,
        **kwargs,
    ) -> List[MemoryEntry]:
        """Ask LLM to consolidate *messages* into a memory_update string.

        Returns a single ``MemoryEntry`` whose ``content`` is the full
        replacement text for MEMORY.md.
        """
        if self.llm is None:
            logger.warning("[tool_extractor] No LLM configured — skipping")
            return []

        template = FLUSH_SYSTEM_PROMPT if is_flush else CONSOLIDATION_SYSTEM_PROMPT
        system_content = template.format(
            current_memory=current_memory or "(empty)",
            char_limit=self.config.char_limit,
        )

        from ms_agent.llm.utils import Message
        llm_messages = [Message(role="system", content=system_content)]
        for m in messages:
            if isinstance(m, Message):
                llm_messages.append(m)
            elif isinstance(m, dict):
                llm_messages.append(Message(
                    role=m.get("role", "user"),
                    content=m.get("content", ""),
                ))

        tool_def = SAVE_MEMORY_TOOL["function"]
        tools = [{
            "tool_name": tool_def["name"],
            "description": tool_def["description"],
            "parameters": tool_def["parameters"],
        }]

        try:
            response = self.llm.generate(
                llm_messages, tools=tools,
                tool_choice={"type": "function",
                             "function": {"name": "save_memory"}},
            )
            # Handle streaming generator
            if hasattr(response, '__next__'):
                for msg in response:
                    response = msg
        except Exception as e:
            logger.warning(f"[tool_extractor] LLM call failed: {e}")
            return []

        memory_update = self._parse_tool_response(response)
        if not memory_update:
            logger.warning("[tool_extractor] No memory_update in response")
            return []

        return [MemoryEntry(
            id="consolidation",
            content=memory_update,
            category="knowledge",
            confidence=1.0,
            source="consolidation",
        )]

    @staticmethod
    def _parse_tool_response(response) -> Optional[str]:
        """Extract ``memory_update`` from the LLM's tool call response."""
        if not hasattr(response, 'tool_calls') or not response.tool_calls:
            if hasattr(response, 'content') and response.content:
                return response.content
            return None
        for tc in response.tool_calls:
            if isinstance(tc, dict):
                name = tc.get("tool_name", "") or tc.get("function", {}).get("name", "")
                args = tc.get("arguments", "{}")
            else:
                name = getattr(tc, "tool_name", "")
                args = getattr(tc, "arguments", "{}")

            if name == "save_memory":
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        return args
                if isinstance(args, dict):
                    return args.get("memory_update")
        return None
