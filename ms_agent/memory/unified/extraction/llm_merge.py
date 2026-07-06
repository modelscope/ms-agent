"""LLMMergeExtractor — Phase 2 deer-flow style LLM-as-merge for facts.json.

The LLM receives the recent conversation + existing facts and outputs
a structured ``{ "newFacts": [...], "factsToRemove": [...] }`` delta.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger

from ..config import MemoryConfig
from ..protocols import MemoryEntry

logger = get_logger()

MERGE_SYSTEM_PROMPT = """\
You are a fact extraction assistant. Analyze the conversation below and \
produce a JSON update for the user's fact database.

Existing facts:
{existing_facts}

Output a JSON object with exactly two keys:
- "newFacts": list of objects, each with "content" (string), "category" \
(one of: preference, knowledge, context, behavior, goal, correction), \
and "confidence" (float 0.0-1.0).
- "factsToRemove": list of fact IDs (strings) that are now outdated, \
contradicted, or duplicated by new facts.

Guidelines:
- Only extract discrete, standalone facts (not summaries or narratives).
- Assign high confidence (0.9-1.0) to corrections and explicit preferences.
- If the user corrects a previous statement, include a "correction" fact \
AND add the old fact's ID to factsToRemove.
- Do NOT duplicate existing facts. If a new fact is equivalent to an \
existing one, skip it or update confidence.
- Output ONLY valid JSON. No markdown, no explanation."""


class LLMMergeExtractor:
    """Produces a structured ``newFacts`` / ``factsToRemove`` delta."""

    def __init__(self, config: MemoryConfig, llm=None):
        self.config = config
        self.llm = llm

    def set_llm(self, llm) -> None:
        self.llm = llm

    async def extract(
        self, messages: List[Dict[str, Any]],
        existing_facts: str = "[]",
        **kwargs,
    ) -> List[MemoryEntry]:
        """Return new facts extracted from *messages*.

        The caller (MemoryUpdateQueue) is responsible for reading
        ``factsToRemove`` from ``entry.metadata`` and applying deletions.
        """
        if self.llm is None:
            logger.warning("[llm_merge] No LLM configured — skipping")
            return []

        system_content = MERGE_SYSTEM_PROMPT.format(
            existing_facts=existing_facts or "[]",
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

        try:
            response = self.llm.generate(llm_messages)
            if hasattr(response, '__next__'):
                for msg in response:
                    response = msg
        except Exception as e:
            logger.warning(f"[llm_merge] LLM call failed: {e}")
            return []

        content = getattr(response, "content", "") or ""
        return self._parse_merge_response(content)

    @staticmethod
    def _parse_merge_response(text: str) -> List[MemoryEntry]:
        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[llm_merge] Failed to parse JSON: {text[:200]}")
            return []

        entries: List[MemoryEntry] = []
        facts_to_remove = data.get("factsToRemove", [])

        for fact in data.get("newFacts", []):
            entry = MemoryEntry(
                content=fact.get("content", ""),
                category=fact.get("category", "knowledge"),
                confidence=float(fact.get("confidence", 0.8)),
                source="llm_merge",
                metadata={"factsToRemove": facts_to_remove},
            )
            if entry.content.strip():
                entries.append(entry)

        return entries
