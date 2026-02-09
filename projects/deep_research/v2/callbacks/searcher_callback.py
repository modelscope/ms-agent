# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
import uuid
from typing import Any, List, Optional

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class SearcherCallback(Callback):
    """
    Callback for Searcher agent.

    Responsibilities:
    - on_task_begin: Clean up system prompt formatting
    - on_task_end: Save the final search result to file
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.output_dir = getattr(config, 'output_dir', './output')
        self.search_task_id: Optional[str] = None
        self.search_result_path = os.path.join(
            self.output_dir, f'search_result_{uuid.uuid4().hex[:4]}.json')
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception as e:
            logger.warning(
                f'Failed to create output_dir {self.output_dir!r}: {e}')

    @staticmethod
    def _sanitize_task_id(task_id: Any, max_len: int = 10) -> Optional[str]:
        """
        Sanitize user-provided task_id to a safe filename component.

        This prevents path traversal (e.g. "../../x") and illegal filenames.
        """
        if task_id is None:
            return None
        s = str(task_id).strip()
        if not s:
            return None
        s = s.replace(os.sep, '_')
        if os.altsep:
            s = s.replace(os.altsep, '_')
        s = re.sub(r'\s+', '_', s)
        s = re.sub(r'[^0-9A-Za-z._-]+', '_', s)
        s = s.strip('._-')[:max_len]
        return s or None

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """Clean up system prompt formatting."""
        for message in messages:
            if message.role == 'system':
                # Remove escaped newlines that might interfere with rendering
                if isinstance(message.content, str):
                    message.content = message.content.replace('\\\n', '')
            elif message.role == 'user':
                try:
                    if not isinstance(message.content, str):
                        continue
                    search_task_description = json.loads(message.content)
                    raw_task_id = search_task_description.get(
                        'task_id') or search_task_description.get('任务ID')
                    safe_task_id = self._sanitize_task_id(raw_task_id)
                    self.search_task_id = safe_task_id
                    if safe_task_id:
                        self.search_result_path = os.path.join(
                            self.output_dir,
                            f'search_result_{safe_task_id}.json')
                except json.JSONDecodeError:
                    logger.warning(
                        f'Failed to parse search task description: {message.content}'
                    )
                    continue
                except Exception as e:
                    logger.warning(
                        f'Unexpected error when parsing search task description: {message.content}, '
                        f'with error: {e}')
                    continue

    async def on_generate_response(self, runtime: Runtime,
                                   messages: List[Message]):
        """
        Inject a round-aware reminder into the system prompt near max rounds.

        Motivation:
        - The model does not inherently know `runtime.round` unless we tell it in the prompt.
        - When approaching `max_chat_round`, remind it to converge: summarize and prepare final JSON.

        Config (optional, in agent yaml):
          round_reminder:
            enabled: true
            remind_before_max_round: 2        # default
            remind_at_round: 28               # overrides computed threshold if set
            message: |                        # optional custom reminder text
              ...
        """
        max_chat_round = getattr(self.config, 'max_chat_round', None)
        if not isinstance(max_chat_round, int):
            try:
                max_chat_round = int(max_chat_round)
            except Exception:
                return

        round_reminder_cfg = getattr(self.config, 'round_reminder', None)
        enabled = False
        remind_before = 2
        remind_at_round = None
        custom_message = None
        if round_reminder_cfg is not None:
            enabled = bool(getattr(round_reminder_cfg, 'enabled', False))
            remind_before = getattr(round_reminder_cfg,
                                    'remind_before_max_round', remind_before)
            remind_at_round = getattr(round_reminder_cfg, 'remind_at_round',
                                      None)
            custom_message = getattr(round_reminder_cfg, 'message', None)

        if not enabled:
            return

        if remind_at_round is None:
            try:
                remind_before_int = int(remind_before)
            except Exception:
                remind_before_int = 2
            remind_at_round = max_chat_round - remind_before_int
        else:
            try:
                remind_at_round = int(remind_at_round)
            except Exception:
                return

        # `runtime.round` counts completed steps; at the beginning of a step it's the current step index.
        if runtime.round != remind_at_round:
            return

        # Append reminder message to the end of the messages.
        reminder_mark = '\n[ROUND_REMINDER]\n'
        # Avoid injecting duplicates (e.g. if resumed from history at the same round).
        for m in reversed(messages[-10:]):
            if m.role == 'user' and isinstance(
                    m.content, str) and '[ROUND_REMINDER]' in m.content:
                return

        remaining = max_chat_round - runtime.round
        if not custom_message or not isinstance(custom_message, str):
            custom_message = (
                '你已接近最大允许的对话轮数上限，请立刻开始收敛准备最终交付。\n'
                '- 从现在开始：优先总结已有证据与进度、补齐关键缺口、减少发散探索。\n'
                '- 在接下来的极少数轮次内，立刻准备并输出最终的 JSON 回复。\n'
                '- 当前轮次信息：round=<round>，max_chat_round=<max_chat_round>，剩余≈<remaining_rounds> 轮。'
            )

        injected = custom_message
        injected = injected.replace('<round>', str(runtime.round))
        injected = injected.replace('<max_chat_round>', str(max_chat_round))
        injected = injected.replace('<remaining_rounds>', str(remaining))
        messages.append(
            Message(role='user', content=reminder_mark + injected + '\n'))

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """
        Save the final search result to file.
        Supports JSON format with fallback to markdown.
        """
        self._ensure_output_dir()
        json_path = self.search_result_path
        md_path = (json_path[:-5]
                   + '.md') if json_path.endswith('.json') else (
                       json_path.split('.')[0] + '.md')
        if os.path.exists(json_path) or os.path.exists(md_path):
            logger.info(
                f'Search result already exists at {json_path} or {md_path}')
            return

        # Find the last assistant message without tool calls
        for message in reversed(messages):
            if message.role == 'assistant' and not message.tool_calls:
                content = message.content
                if not content:
                    continue

                try:
                    # Prefer JSON file if possible; fallback to markdown otherwise.
                    if isinstance(content, str):
                        parsed_json = json.loads(content)
                    else:
                        parsed_json = content
                    try:
                        with open(json_path, 'x', encoding='utf-8') as f:
                            json.dump(
                                parsed_json, f, ensure_ascii=False, indent=2)
                        logger.info(
                            f'Searcher: Search result saved to {json_path}')
                    except FileExistsError:
                        logger.info(
                            f'Search result already exists at {json_path}')
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        'Failed to parse search result as JSON, saving as markdown'
                    )
                    text = content if isinstance(content,
                                                 str) else str(content)
                    try:
                        with open(md_path, 'x', encoding='utf-8') as f:
                            f.write(text)
                        logger.info(
                            f'Searcher: Search result saved to {md_path}')
                    except FileExistsError:
                        logger.info(
                            f'Search result already exists at {md_path}')
                except Exception as e:
                    logger.warning(
                        f'Unexpected error when saving search result: {e}')
                return

        logger.warning('Searcher: No final search result found in messages')
