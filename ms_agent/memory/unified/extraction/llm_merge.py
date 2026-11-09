"""LLMMergeExtractor — Phase 2 deer-flow style LLM-as-merge for facts.json.

The LLM receives the recent conversation + existing facts and outputs
a structured ``{ "newFacts": [...], "factsToRemove": [...] }`` delta.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from ms_agent.utils.logger import get_logger
from ..config import MemoryConfig
from ..protocols import MemoryEntry
from .tool_based import (_collect_in_executor, _evidence_batches,
                         _evidence_messages, _generation_options)

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
        self,
        messages: List[Dict[str, Any]],
        existing_facts: str = '[]',
        **kwargs,
    ) -> List[MemoryEntry]:
        """Return new facts extracted from *messages*.

        The caller (MemoryUpdateQueue) is responsible for reading
        ``factsToRemove`` from ``entry.metadata`` and applying deletions.
        """
        if self.llm is None:
            raise RuntimeError('[llm_merge] No LLM configured')

        system_content = MERGE_SYSTEM_PROMPT.format(
            existing_facts=existing_facts or '[]', )
        batches = await asyncio.to_thread(_evidence_batches, self.llm,
                                          self.config, messages,
                                          system_content)
        facts = json.loads(existing_facts or '[]')
        entries, removed = [], set()
        for batch in batches:
            system_content = MERGE_SYSTEM_PROMPT.format(
                existing_facts=json.dumps(facts, ensure_ascii=False))
            llm_messages = _evidence_messages(system_content, batch)
            options = _generation_options(self.llm, self.config, llm_messages)
            response = await _collect_in_executor(
                self.llm, llm_messages, max_continue_runs=0, **options)
            if getattr(response, 'finish_reason',
                       '') in ('length', 'max_tokens'):
                raise ValueError(
                    'Truncated memory update; existing facts retained')
            additions = self._parse_merge_response(
                getattr(response, 'content', '') or '')
            for entry in additions:
                removed.update(entry.metadata.get('factsToRemove', []))
            entries = [e for e in entries if e.id not in removed]
            entries.extend(e for e in additions if e.content.strip())
            facts = [f for f in facts if f.get('id') not in removed]
            facts.extend(e.to_dict() for e in additions if e.content.strip())
        if removed:
            entries.append(
                MemoryEntry(
                    content='',
                    source='llm_merge',
                    metadata={'factsToRemove': sorted(removed)}))
        return entries

    @staticmethod
    def _parse_merge_response(text: str) -> List[MemoryEntry]:
        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith('```'):
            lines = text.split('\n')
            lines = [
                line for line in lines if not line.strip().startswith('```')
            ]
            text = '\n'.join(lines)

        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(
                data.get('newFacts'), list):
            raise ValueError(
                'Invalid memory merge response: expected newFacts list')
        facts_to_remove = data.get('factsToRemove')
        if not isinstance(facts_to_remove, list) or not all(
                isinstance(value, str) for value in facts_to_remove):
            raise ValueError(
                'Invalid memory merge response: expected fact IDs')
        entries: List[MemoryEntry] = []

        for fact in data['newFacts']:
            entry = MemoryEntry(
                content=fact.get('content', ''),
                category=fact.get('category', 'knowledge'),
                confidence=float(fact.get('confidence', 0.8)),
                source='llm_merge',
                metadata={'factsToRemove': facts_to_remove},
            )
            if entry.content.strip():
                entries.append(entry)

        if not entries and facts_to_remove:
            # Carry a deletion-only delta without persisting an empty fact.
            entries.append(
                MemoryEntry(
                    content='',
                    source='llm_merge',
                    metadata={'factsToRemove': facts_to_remove}))
        return entries


async def apply_fact_updates(storage, entries):
    removed = []
    for entry in entries:
        for fact_id in entry.metadata.get('factsToRemove', []):
            if fact_id not in removed:
                removed.append(fact_id)
    facts = [entry for entry in entries if entry.content.strip()]
    await storage.apply_merge(facts, removed)
