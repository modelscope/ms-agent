# Copyright (c) ModelScope Contributors. All rights reserved.

from copy import copy
from typing import List, Optional

from ms_agent.llm import LLM, Message, token_budget
from ms_agent.memory import Memory
from ms_agent.utils.logger import logger

# Default summary prompt template (from opencode)
SUMMARY_PROMPT = """Summarize this conversation to help continue the work.

Focus on:
- Goal: What is the user trying to accomplish?
- Instructions: Important user requirements or constraints
- Discoveries: Notable findings during the conversation
- Accomplished: What's done, in progress, and remaining
- Relevant files: Files read, edited, or created

Keep it concise but comprehensive enough for another agent to continue."""


class ContextCompressor(Memory):
    """Context Compressor - Inspired by opencode's context compaction mechanism.

    Core concepts:
    1. Token overflow detection - Monitor token usage against context limits
    2. Tool output pruning - Compress old tool call outputs to save context
    3. Summary compaction - Use LLM to generate conversation summary

    Reference: opencode/packages/opencode/src/session/compaction.ts
    """

    def __init__(self, config):
        super().__init__(config)
        mem_config = getattr(config.memory, 'context_compressor', None)
        if mem_config is None:
            mem_config = config.memory

        # Token thresholds (inspired by opencode's PRUNE constants)
        self.context_limit = getattr(mem_config, 'context_limit', 128000)
        self.prune_protect = getattr(mem_config, 'prune_protect', 40000)
        self.prune_minimum = getattr(mem_config, 'prune_minimum', 20000)
        self.reserved_buffer = getattr(mem_config, 'reserved_buffer', 20000)

        # Summary prompt
        self.summary_prompt = getattr(mem_config, 'summary_prompt',
                                      SUMMARY_PROMPT)

        # LLM for summarization
        self.llm: Optional[LLM] = None
        self._last_summary_attempt = None
        if getattr(mem_config, 'enable_summary', True):
            try:
                self.llm = LLM.from_config(config)
            except Exception as e:
                logger.warning(f'Failed to init LLM for summary: {e}')

    def estimate_tokens(self, text: str) -> int:
        """Estimate text consistently with session compaction."""
        return token_budget.estimate_text_tokens(text)

    def _estimate_message_tokens_from_content(self, msg: Message) -> int:
        """Heuristic token count from message body (no API usage fields)."""
        return token_budget.estimate_message_tokens(msg)

    def estimate_message_tokens(self, msg: Message) -> int:
        """Tokens for one message: prefer ``Message`` usage, else content heuristic."""
        return token_budget.estimate_total_tokens([msg])

    def estimate_total_tokens(self, messages: List[Message]) -> int:
        """Total tokens for the conversation."""
        return token_budget.estimate_total_tokens(messages)

    def is_overflow(self, messages: List[Message]) -> bool:
        """Check if messages exceed context limit."""
        total = self.estimate_total_tokens(messages)
        usable = self.context_limit - self.reserved_buffer
        return total >= usable

    def prune_tool_outputs(self, messages: List[Message]) -> List[Message]:
        """Prune old tool outputs to reduce context size.

        Strategy (from opencode):
        - Scan backwards through messages
        - Protect the most recent tool outputs (prune_protect tokens)
        - Truncate older tool outputs
        """
        total_tool_tokens = 0
        pruned_count = 0
        messages = [copy(m) for m in messages]

        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.role != 'tool' or not (msg.content or msg.attachments):
                continue
            tokens = token_budget.estimate_message_tokens(msg)
            total_tool_tokens += tokens

            if total_tool_tokens > self.prune_protect:
                msg.content = '[Output truncated to save context]'
                msg.attachments = []
                pruned_count += 1

        if pruned_count > 0:
            # Usage belongs to the pre-pruned request, not this new view.
            for msg in messages:
                msg.prompt_tokens = msg.completion_tokens = 0
                msg.usage_records = []
            logger.info(f'Pruned {pruned_count} tool outputs')

        return messages

    def summarize(self, messages: List[Message]) -> Optional[str]:
        """Generate conversation summary using LLM."""
        if not self.llm:
            return None

        # Build conversation text for summarization
        conv_parts = []
        for msg in messages:
            role = msg.role.upper()
            content = token_budget.summary_text(msg)
            if content:
                conv_parts.append(f'{role}: {content[:2000]}')

        conversation = '\n'.join(conv_parts)
        query = f'{self.summary_prompt}\n\n---\n{conversation}'

        try:
            response = self.llm.generate([Message(role='user', content=query)],
                                         stream=False)
            return response.content
        except Exception as e:
            logger.error(f'Summary generation failed: {e}')
            return None

    def compress(self, messages: List[Message]) -> List[Message]:
        """Compress messages when context overflows.

        Steps:
        1. Try pruning tool outputs first
        2. If still overflow, generate summary and replace history
        """
        if not self.is_overflow(messages):
            return messages

        logger.info('Context overflow detected, starting compression')

        # Step 1: Prune tool outputs
        pruned = self.prune_tool_outputs(messages)
        if not self.is_overflow(pruned):
            return pruned

        usable = self.context_limit - self.reserved_buffer
        key = token_budget.summary_attempt_key(pruned, usable)
        if key == self._last_summary_attempt:
            return pruned
        self._last_summary_attempt = key
        protected = [m for m in pruned if m.role == 'system'][:1]
        if pruned and pruned[-1].role == 'user':
            protected.append(pruned[-1])
        if sum(token_budget.estimate_message_tokens(m)
               for m in protected) >= usable:
            logger.warning('Context budget is exceeded by protected messages; '
                           'summary cannot make this request fit')
            return pruned

        # Step 2: Generate summary
        summary = self.summarize(pruned)
        if not summary:
            logger.warning('Summary failed, returning pruned messages')
            return pruned

        # Keep system prompt and replace history with summary
        result = []
        for msg in messages:
            if msg.role == 'system':
                result.append(msg)
                break

        result.append(
            Message(
                role='user',
                content=f'[Conversation Summary]\n{summary}\n\n'
                'Please continue based on this summary.'))

        # Keep the most recent user message if different
        if messages and messages[-1].role == 'user':
            last_user = messages[-1]
            if ((last_user.content or last_user.attachments)
                    and last_user.content != result[-1].content):
                result.append(last_user)

        if self.estimate_total_tokens(result) >= self.estimate_total_tokens(
                pruned):
            logger.warning(
                'Summary did not reduce the context budget; keeping the original view'
            )
            return pruned

        logger.info(
            f'Compressed {len(messages)} messages to {len(result)} messages')
        return result

    async def run(self, messages: List[Message]) -> List[Message]:
        """Main entry point for context compression."""
        return self.compress(messages)
