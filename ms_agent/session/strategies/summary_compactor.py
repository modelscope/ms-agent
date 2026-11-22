"""SummaryCompactor — LLM-based conversation summary when token pressure exceeds pruning.

Migrated from ``ContextCompressor.summarize`` / ``compress``.  This strategy
replaces old messages with a summary message and advances
``last_consolidated``, but the original data is preserved in the SessionLog.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ms_agent.llm import token_budget
from ms_agent.utils.logger import get_logger

logger = get_logger()

SUMMARY_PROMPT = """Summarize this conversation to help continue the work.

Focus on:
- Goal: What is the user trying to accomplish?
- Instructions: Important user requirements or constraints
- Discoveries: Notable findings during the conversation
- Accomplished: What's done, in progress, and remaining
- Relevant files: Files read, edited, or created

Preserve verbatim, never rewrite or drop: the LATEST <system-reminder>
skill-update notice, if any (it is the authoritative current skill list),
and the LATEST <system-reminder> notice about changed workspace/prompt
files, if any (it explains why earlier conversation may reference outdated
file contents). Other <system-reminder> blocks (e.g. retrieved memories)
are ordinary context — summarize or drop them like anything else.

Keep it concise but comprehensive enough for another agent to continue."""

SUMMARY_INPUT_CHAR_LIMIT = 2000


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // 4


def _estimate_message_tokens(msg: Dict[str, Any]) -> int:
    """Shared text/media heuristic, excluding API usage anchors."""
    return token_budget.estimate_message_tokens(msg)


def _estimate_total_tokens(messages: List[Dict[str, Any]]) -> int:
    """Estimate total tokens, preferring real API usage data when available.

    ``prompt_tokens`` on an assistant message already accounts for all
    preceding context in that API call, so we use it as a base and only
    add a heuristic for messages appended *after* that turn.
    """
    return token_budget.estimate_total_tokens(messages)


class SummaryCompactor:
    """Replace the oldest portion of the visible window with an LLM summary.

    Configuration keys (in ``config`` dict):
    - ``context_limit``:  max context tokens (default 128000)
    - ``reserved_buffer``: buffer before triggering (default 20000)
    - ``summary_prompt``: custom summarization prompt

    The compactor needs an LLM instance to generate summaries.  Pass it via
    the constructor or set ``self.llm`` before use.
    """

    name = 'summary_compactor'

    def __init__(self, llm: Any = None) -> None:
        self.llm = llm
        self._last_summary_attempt = None

    def apply(
        self,
        visible: List[Dict[str, Any]],
        all_msgs: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        context_limit = config.get('context_limit', 128000)
        reserved = config.get('reserved_buffer', 20000)
        usable = context_limit - reserved

        tokens_before = _estimate_total_tokens(visible)
        if tokens_before < usable:
            return visible, None

        if not self.llm:
            logger.warning('[summary_compactor] No LLM available, skipping')
            return visible, None

        key = token_budget.summary_attempt_key(visible, usable)
        if key == self._last_summary_attempt:
            return visible, None
        self._last_summary_attempt = key
        protected = [m for m in visible if m.get('role') == 'system'][:1]
        if visible and visible[-1].get('role') == 'user':
            protected.append(visible[-1])
        if sum(_estimate_message_tokens(m) for m in protected) >= usable:
            logger.warning(
                '[summary_compactor] Protected messages exceed the '
                'context budget; summary cannot make this request fit')
            return visible, None

        summary = self._generate_summary(visible, config)
        if not summary:
            return visible, None

        # Keep system message and most recent messages; replace middle
        result: List[Dict[str, Any]] = []
        for msg in visible:
            if msg.get('role') == 'system':
                result.append(msg)
                break

        result.append({
            'role':
            'user',
            'content':
            f'[Conversation Summary]\n{summary}\n\n'
            'Please continue based on this summary.',
        })

        if visible and visible[-1].get('role') == 'user':
            last_user = visible[-1]
            if ((last_user.get('content') or last_user.get('attachments'))
                    and last_user.get('content') != result[-1]['content']):
                result.append(last_user)

        tokens_after = _estimate_total_tokens(result)
        if tokens_after >= tokens_before:
            logger.warning('[summary_compactor] Summary did not reduce the '
                           'context budget; keeping the original view')
            return visible, None

        logger.info(
            f'[summary_compactor] Compressed {len(visible)} messages to '
            f'{len(result)} ({tokens_before} -> {tokens_after} tokens)')

        return result, {
            'summary': summary[:200],
            'tokens_before': tokens_before,
            'tokens_after': tokens_after,
        }

    def _generate_summary(self, messages: List[Dict[str, Any]],
                          config: Dict[str, Any]) -> Optional[str]:
        prompt = config.get('summary_prompt', SUMMARY_PROMPT)
        char_limit = config.get('summary_input_char_limit',
                                SUMMARY_INPUT_CHAR_LIMIT)
        conv_parts: List[str] = []
        for msg in messages:
            role = msg.get('role', '?').upper()
            # Reduce a block list to its text instead of skipping the message:
            # a turn dropped here is invisible to the summary that decides what
            # survives compaction.
            content = token_budget.summary_text(msg)
            if content:
                conv_parts.append(f'{role}: {content[:char_limit]}')

        conversation = '\n'.join(conv_parts)
        query = f'{prompt}\n\n---\n{conversation}'

        try:
            from ms_agent.llm.utils import Message
            response = self.llm.generate([Message(role='user', content=query)],
                                         stream=False)
            return response.content
        except Exception as e:
            logger.error(f'[summary_compactor] Summary generation failed: {e}')
            return None
