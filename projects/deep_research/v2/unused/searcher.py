# Copyright (c) Alibaba, Inc. and its affiliates.
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


@dataclass
class _CompactionConfig:
    enabled: bool = True
    max_total_chars: int = 220_000
    max_messages: int = 120
    max_prompt_tokens: int = 60_000
    keep_tail_messages: int = 18
    summary_max_tokens: int = 1_200
    summary_model: Optional[str] = None
    prune_tool_outputs: bool = True
    tool_keep_last: int = 6
    tool_max_chars: int = 2_500


class SearcherAgent(LLMAgent):
    """
    SearcherAgent: LLMAgent with in-loop "memory compaction" for long-running search cycles.

    Key goals:
    - Do NOT modify LLMAgent.
    - Before each LLM call, if history is too large, summarize the middle history into one assistant
      message, keeping the system + initial task + recent tail intact.
    - Optionally prune old tool outputs to reduce prompt size while keeping recent tool context.
    """

    SUMMARY_NAME = 'memory_summary'
    SUMMARY_PREFIX = '【历史摘要（自动压缩）】'
    TOOL_PRUNE_PREFIX = '[Tool output pruned to save context]'

    def _get_compaction_cfg(self) -> _CompactionConfig:
        cfg = getattr(self.config, 'compaction', DictConfig({}))
        return _CompactionConfig(
            enabled=bool(getattr(cfg, 'enabled', True)),
            max_total_chars=int(getattr(cfg, 'max_total_chars', 220_000)),
            max_messages=int(getattr(cfg, 'max_messages', 120)),
            max_prompt_tokens=int(getattr(cfg, 'max_prompt_tokens', 60_000)),
            keep_tail_messages=int(getattr(cfg, 'keep_tail_messages', 18)),
            summary_max_tokens=int(getattr(cfg, 'summary_max_tokens', 1_200)),
            summary_model=getattr(cfg, 'summary_model', None),
            prune_tool_outputs=bool(getattr(cfg, 'prune_tool_outputs', True)),
            tool_keep_last=int(getattr(cfg, 'tool_keep_last', 6)),
            tool_max_chars=int(getattr(cfg, 'tool_max_chars', 2_500)),
        )

    @staticmethod
    def _safe_text(x) -> str:
        if x is None:
            return ''
        if isinstance(x, str):
            return x
        # Some message.content might be list[dict] in other flows; stringify safely.
        try:
            return str(x)
        except Exception:
            return ''

    @classmethod
    def _msg_char_size(cls, m: Message) -> int:
        return (len(cls._safe_text(m.content))
                + len(getattr(m, 'reasoning_content', '') or '')
                + len(getattr(m, 'name', '') or ''))

    @classmethod
    def _total_char_size(cls, messages: List[Message]) -> int:
        return sum(cls._msg_char_size(m) for m in messages)

    @classmethod
    def _find_summary_idx(cls, messages: List[Message]) -> Optional[int]:
        for i, m in enumerate(messages):
            if m.role == 'assistant' and (m.name == cls.SUMMARY_NAME):
                return i
        return None

    @classmethod
    def _truncate_text(cls, text: str, limit: int) -> str:
        if limit <= 0:
            return text
        if len(text) <= limit:
            return text
        head = text[:max(0, limit - 500)]
        tail = text[-500:] if len(text) > 500 else ''
        return f'{head}\n...\n{tail}'

    def _should_compact(self, messages: List[Message],
                        cfg: _CompactionConfig) -> bool:
        if not cfg.enabled:
            return False
        if len(messages) >= cfg.max_messages:
            return True
        if self._total_char_size(messages) >= cfg.max_total_chars:
            return True
        # Optional: use last assistant's reported prompt_tokens as a signal
        for m in reversed(messages):
            if m.role == 'assistant':
                pt = getattr(m, 'prompt_tokens', 0) or 0
                if pt and pt >= cfg.max_prompt_tokens:
                    return True
                break
        return False

    def _prune_old_tool_outputs(self, messages: List[Message],
                                cfg: _CompactionConfig) -> None:
        if not cfg.prune_tool_outputs:
            return
        # Keep last N tool messages unchanged; prune older tool message contents.
        tool_indices = [i for i, m in enumerate(messages) if m.role == 'tool']
        if len(tool_indices) <= cfg.tool_keep_last:
            return
        to_prune = tool_indices[:max(0,
                                     len(tool_indices) - cfg.tool_keep_last)]
        for i in to_prune:
            m = messages[i]
            raw = self._safe_text(m.content)
            if not raw:
                continue
            truncated = self._truncate_text(raw, cfg.tool_max_chars)
            if truncated != raw:
                m.content = f'{self.TOOL_PRUNE_PREFIX}\n\n{truncated}'

    def _format_for_summary(self, messages: List[Message],
                            cfg: _CompactionConfig) -> str:
        # Reduce tool payloads in the summarizer input to avoid blowing up again.
        blocks: List[str] = []
        for m in messages:
            role = m.role
            name = f' ({m.name})' if getattr(m, 'name', None) else ''
            content = self._safe_text(m.content)
            if role == 'tool':
                content = self._truncate_text(content,
                                              min(cfg.tool_max_chars, 1500))
            else:
                content = self._truncate_text(content, 6000)
            blocks.append(f'[{role}{name}]\n{content}'.strip())
        return '\n\n'.join(blocks)

    def _summarize_middle_history(self, middle: List[Message],
                                  cfg: _CompactionConfig) -> Optional[str]:
        if not middle:
            return None
        assert self.llm is not None, 'LLM must be initialized before compaction.'

        system = ('你是一个对话历史压缩器。你的任务是把被截断的历史对话压缩成一个可继续对话的摘要。'
                  '要求：\n'
                  '1) 只保留对后续搜索/证据收集/写报告必要的信息；\n'
                  '2) 明确记录：任务目标/范围/验收标准；当前进度；关键发现与证据要点；'
                  '已写入的 note_id / 文件路径；尚未解决的问题与下一步计划；\n'
                  '3) 不要编造事实；不确定就标注不确定；\n'
                  '4) 输出为中文纯文本，尽量精炼但信息密度高。')
        user = '请压缩下面的历史内容：\n\n' + self._format_for_summary(middle, cfg)

        messages_sum = [
            Message(role='system', content=system),
            Message(role='user', content=user),
        ]

        try:
            resp = self.llm.generate(
                messages_sum,
                stream=False,
                max_tokens=cfg.summary_max_tokens,
                model=cfg.summary_model,
            )
            text = (resp.content or '').strip()
            if not text:
                return None
            if not text.startswith(self.SUMMARY_PREFIX):
                text = f'{self.SUMMARY_PREFIX}\n{text}'
            return text
        except Exception as e:
            logger.warning(
                f'[{self.tag}] compaction summarization failed: {e}')
            return None

    def _compact_messages(self, messages: List[Message],
                          cfg: _CompactionConfig) -> List[Message]:
        # Expected baseline: [system, user, ...]
        if len(messages) < 4:
            return messages

        # Always keep system + the initial user task message intact.
        system_msg = messages[0]
        first_user_msg = messages[1]

        keep_tail = max(0, cfg.keep_tail_messages)
        tail_start = max(2, len(messages) - keep_tail)

        # Don't compact if there is no middle.
        if tail_start <= 2:
            return messages

        summary_idx = self._find_summary_idx(messages)
        middle_start = summary_idx if summary_idx is not None else 2
        middle = messages[middle_start:tail_start]
        if not middle:
            return messages

        summary_text = self._summarize_middle_history(middle, cfg)
        if not summary_text:
            return messages

        summary_msg = Message(
            role='assistant', content=summary_text, name=self.SUMMARY_NAME)

        # Construct: system, first_user, summary, tail
        new_messages = [system_msg, first_user_msg, summary_msg
                        ] + messages[tail_start:]
        return new_messages

    async def condense_memory(self, messages: List[Message]) -> List[Message]:
        # Keep existing memory tools behavior (if any).
        messages = await super().condense_memory(messages)

        cfg = self._get_compaction_cfg()
        if not self._should_compact(messages, cfg):
            return messages

        # First prune old tool outputs (cheap win), then compact.
        self._prune_old_tool_outputs(messages, cfg)
        messages = self._compact_messages(messages, cfg)
        return messages
