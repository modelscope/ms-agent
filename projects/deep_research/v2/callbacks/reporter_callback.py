# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import re
from typing import Any, Dict, List, Optional, Set

import json
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from ms_agent.utils.constants import DEFAULT_MEMORY_DIR
from omegaconf import DictConfig

logger = get_logger()


class ReporterCallback(Callback):
    """
    Callback for Reporter agent.

    Responsibilities:
    - on_task_begin: Clean up system prompt formatting and load researcher trajectory
    - on_task_end: Save the final report to file
    """

    # The tag of the main researcher agent whose history we want to load
    RESEARCHER_TAG = 'deep-research-researcher'

    # Tool names to exclude from trajectory (reporter_tool calls and their responses)
    EXCLUDED_TOOL_PATTERNS = ['reporter_tool']

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.output_dir = getattr(config, 'output_dir', './output')
        self.reports_dir = 'reports'

        # Get reports_dir from tool config if available
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'report_generator'):
            report_cfg = config.tools.report_generator
            self.reports_dir = getattr(report_cfg, 'reports_dir', 'reports')

        self.report_path = os.path.join(self.output_dir, self.reports_dir,
                                        'report.md')

    def _load_researcher_history(self) -> Optional[List[Dict[str, Any]]]:
        """
        Load the researcher agent's message history from the memory file.

        Returns:
            List of message dicts, or None if file doesn't exist or fails to load.
        """
        memory_file = os.path.join(self.output_dir, DEFAULT_MEMORY_DIR,
                                   f'{self.RESEARCHER_TAG}.json')

        if not os.path.exists(memory_file):
            logger.warning(f'Researcher memory file not found: {memory_file}. '
                           f'Research trajectory will not be loaded.')
            return None

        try:
            with open(memory_file, 'r', encoding='utf-8') as f:
                messages = json.load(f)
            logger.info(
                f'Loaded {len(messages)} messages from researcher memory.')
            return messages
        except Exception as e:
            logger.warning(f'Failed to load researcher memory: {e}')
            return None

    def _is_reporter_tool_call(self, message: Dict[str, Any]) -> bool:
        """Check if this message contains a call to reporter_tool."""
        tool_calls = message.get('tool_calls') or []
        for tc in tool_calls:
            tool_name = tc.get('tool_name', '') or tc.get('function', {}).get(
                'name', '')
            # NOTE: It's a strict match, consider to use more flexible pattern matching.
            for pattern in self.EXCLUDED_TOOL_PATTERNS:
                if pattern in tool_name:
                    return True
        return False

    def _get_reporter_tool_call_ids(
            self, messages: List[Dict[str, Any]]) -> Set[str]:
        """
        Collect all tool_call_ids that are associated with reporter_tool calls.
        These IDs will be used to filter out the corresponding tool response messages.
        """
        excluded_ids = set()
        for msg in messages:
            if self._is_reporter_tool_call(msg):
                tool_calls = msg.get('tool_calls') or []
                for tc in tool_calls:
                    tool_name = tc.get('tool_name', '') or tc.get(
                        'function', {}).get('name', '')
                    for pattern in self.EXCLUDED_TOOL_PATTERNS:
                        if pattern in tool_name:
                            call_id = tc.get('id')
                            if call_id:
                                excluded_ids.add(call_id)
        return excluded_ids

    def _filter_messages(
            self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out:
        1. System messages (role == 'system')
        2. Assistant messages that call reporter_tool
        3. Tool response messages for reporter_tool calls
        """
        # First pass: collect IDs of reporter_tool calls
        excluded_call_ids = self._get_reporter_tool_call_ids(messages)

        filtered = []
        for msg in messages:
            role = msg.get('role', '')

            # Skip system messages
            if role == 'system':
                continue

            # Skip assistant messages that call reporter_tool
            if role == 'assistant' and self._is_reporter_tool_call(msg):
                continue

            # Skip tool responses for reporter_tool calls
            if role == 'tool':
                tool_call_id = msg.get('tool_call_id')
                if tool_call_id and tool_call_id in excluded_call_ids:
                    continue

            filtered.append(msg)

        return filtered

    def _format_trajectory(self, messages: List[Dict[str, Any]]) -> str:
        """
        Format the filtered messages into a readable research trajectory summary.
        """
        lines = ['# 主代理（Researcher）调研轨迹', '']

        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            tool_calls = msg.get('tool_calls') or []
            tool_name = msg.get('name', '')

            if role == 'user':
                lines.append('## 用户请求')
                lines.append(content[:2000] if content else '(empty)')
                lines.append('')

            elif role == 'assistant':
                if content:
                    lines.append('### 助理思考/回复')
                    lines.append(
                        content[:20000] if len(content) > 20000 else content)
                    lines.append('')

                if tool_calls:
                    lines.append('### 工具调用')
                    for tc in tool_calls:
                        tc_name = tc.get('tool_name', '') or tc.get(
                            'function', {}).get('name', '')
                        tc_args = tc.get('arguments', '')
                        # Truncate long arguments
                        if isinstance(tc_args, str) and len(tc_args) > 20000:
                            tc_args = tc_args[:20000] + '...(truncated)'
                        lines.append(f'- **{tc_name}**: `{tc_args}`')
                    lines.append('')

            elif role == 'tool':
                lines.append(f'### 工具结果 ({tool_name})')
                # Truncate very long tool results
                if content and len(content) > 20000:
                    content = content[:20000] + '\n...(truncated)'
                lines.append(content if content else '(empty)')
                lines.append('')

        return '\n'.join(lines)

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """Clean up system prompt formatting and inject researcher trajectory."""
        for message in messages:
            if message.role == 'system':
                # Remove escaped newlines that might interfere with rendering
                message.content = message.content.replace('\\\n', '')

        # Load researcher's history from memory
        raw_history = self._load_researcher_history()
        if raw_history:
            # Filter out system messages and reporter_tool calls
            filtered_history = self._filter_messages(raw_history)
            logger.info(
                f'Filtered researcher history: {len(raw_history)} -> {len(filtered_history)} messages'
            )

            if filtered_history:
                # Format as readable trajectory
                trajectory_text = self._format_trajectory(filtered_history)

                # Inject as a new user message right after system message
                # Find the position after system message
                insert_pos = 0
                for i, msg in enumerate(messages):
                    if msg.role == 'system':
                        insert_pos = i + 1
                        break

                trajectory_str = (
                    '以下是主代理（Researcher）的调研轨迹，包含了研究过程中的关键决策、'
                    '工具调用和中间结论。请参考这些信息来理解研究背景和约束，'
                    '但报告写作仍需以 evidence_store 中的证据为准，并且注意该轨迹可能存在内容过长导致的截断。\n\n'
                    f'{trajectory_text}')

                if messages[insert_pos].role == 'user':
                    messages[insert_pos].content += f'\n\n{trajectory_str}'
                else:
                    # fallback: 插入独立消息
                    messages.insert(
                        insert_pos,
                        Message(role='user', content=trajectory_str))

                logger.info(
                    f'Injected researcher trajectory ({len(trajectory_text)} chars) '
                    f'into reporter messages at position {insert_pos}')

    def _extract_json_from_content(self,
                                   content: str) -> Optional[Dict[str, Any]]:
        """
        Try to extract JSON from content, handling markdown code blocks.

        Returns:
            Parsed JSON dict, or None if no valid JSON found.
        """
        # First try to parse the entire content as JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block (```json ... ``` or ``` ... ```)
        json_block_pattern = r'```(?:json)?\s*\n?([\s\S]*?)\n?```'
        matches = re.findall(json_block_pattern, content)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

        # Try to find JSON object pattern in content
        # Look for content starting with { and ending with }
        json_object_pattern = r'\{[\s\S]*\}'
        matches = re.findall(json_object_pattern, content)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        return None

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """
        Save the final report to file.
        Supports both JSON and markdown output formats.
        """
        if os.path.exists(self.report_path):
            logger.info(f'Report already exists at {self.report_path}')
            return

        # Find the last assistant message without tool calls
        for message in reversed(messages):
            if message.role == 'assistant' and not message.tool_calls:
                content = message.content
                if not content:
                    continue

                # Ensure directory exists
                os.makedirs(os.path.dirname(self.report_path), exist_ok=True)

                # Try to extract and save JSON result
                json_result = self._extract_json_from_content(content)
                if json_result:
                    # Save the full JSON result
                    json_path = self.report_path.replace('.md', '.json')
                    with open(json_path, 'w', encoding='utf-8') as f:
                        json.dump(json_result, f, ensure_ascii=False, indent=2)
                    logger.info(f'Reporter: JSON result saved to {json_path}')

                    # Also extract and save the Report field as markdown if present
                    report_content = json_result.get(
                        'Report') or json_result.get('report')
                    if report_content:
                        with open(
                                self.report_path, 'w', encoding='utf-8') as f:
                            f.write(report_content)
                        logger.info(
                            f'Reporter: Report content saved to {self.report_path}'
                        )
                    return

                # Fallback: save as markdown if not valid JSON
                with open(self.report_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(
                    f'Reporter: Final report saved to {self.report_path}')
                return

        logger.warning('Reporter: No final report content found in messages')
