# Copyright (c) Alibaba, Inc. and its affiliates.
# yapf: disable
import os
import re
import shutil
from typing import Any, Dict, List, Optional, Set

import json
from callbacks.quality_checker import (ReportQualityChecker,
                                       build_quality_checkers)
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
    - on_generate_response: Inject round-aware reminder near max rounds
    - after_tool_call: Pre-completion quality checks (report existence,
      length retention vs draft, model-based content audit)
    - on_task_end: Promote the best report to final_report.md and save JSON summary
    """

    RESEARCHER_TAG = 'deep-research-researcher'
    EXCLUDED_TOOL_PATTERNS = ['reporter_tool']

    DRAFT_FILENAME = 'draft.md'
    REPORT_FILENAME = 'report.md'
    FINAL_REPORT_FILENAME = 'final_report.md'
    DEFAULT_MIN_RETENTION_RATIO = 0.3

    _ROUND_REMINDER_TEMPLATES = {
        'zh':
        ('你已接近最大允许的对话轮数上限，请立刻开始收敛准备最终交付。\n'
         '- 从现在开始：优先基于已完成撰写的章节、整合的草稿、记录的冲突列表和最新的大纲进行收敛，补齐关键缺口、减少发散探索。\n'
         '- 在接下来的极少数轮次内，必须立刻准备并输出最终的 JSON 回复。\n'
         '- 当前轮次信息：round=<round>，max_chat_round=<max_chat_round>，剩余≈<remaining_rounds> 轮。'
         ),
        'en':
        ('You are approaching the maximum allowed conversation round limit. Begin converging immediately and prepare the final delivery.\n'
         '- From now on: Prioritize converging based on the already completed chapters, assembled drafts, recorded conflict list, and the latest outline. Fill critical gaps and reduce exploratory divergence.\n'
         '- Within the very few remaining rounds, you must immediately prepare and output the final JSON response.\n'
         '- Current round info: round=<round>, max_chat_round=<max_chat_round>, remaining ≈ <remaining_rounds> rounds.'
         ),
    }

    # Bilingual trajectory labels keyed by language code.
    _TRAJECTORY_LABELS = {
        'zh': {
            'title':
            '# 主代理（Researcher）调研轨迹',
            'user_request':
            '## 用户请求',
            'assistant_thinking':
            '### 助理思考/回复',
            'tool_calls':
            '### 工具调用',
            'tool_result':
            '### 工具结果',
            'trajectory_intro':
            ('以下是主代理（Researcher）的调研轨迹，包含了研究过程中的关键决策、'
             '工具调用和中间结论。请参考这些信息来理解研究背景和约束，'
             '但报告写作仍需以 evidence_store 中的证据为准，并且注意该轨迹可能存在内容过长导致的截断。'),
        },
        'en': {
            'title':
            '# Main Agent (Researcher) Research Trajectory',
            'user_request':
            '## User Request',
            'assistant_thinking':
            '### Assistant Thinking/Response',
            'tool_calls':
            '### Tool Calls',
            'tool_result':
            '### Tool Result',
            'trajectory_intro':
            ('Below is the research trajectory of the main agent (Researcher), containing key decisions, '
             'tool calls, and intermediate conclusions during the research process. Please refer to this '
             'information to understand the research background and constraints, but report writing must '
             'still be based on the evidence in evidence_store. Note that this trajectory may be truncated '
             'due to excessive length.'),
        },
    }

    _REFLECTION_TEMPLATES = {
        'zh': {
            'no_report':
            ('外部检查发现：输出目录中尚未检测到已完成的报告文件 reports/report.md。\n'
             '请确认报告写作流程是否已完成。你应当至少完成以下步骤：\n'
             '1. 完成所有章节的撰写\n'
             '2. 调用 report_generator---assemble_draft 生成报告草稿\n'
             '3. 审阅草稿并交付最终版本\n'
             '请立即采取行动完成报告交付。'),
            'over_compressed':
            ('外部检查发现：reports/{report_name} 的内容量（{report_chars} 字符）'
             '仅为 reports/draft.md（{draft_chars} 字符）的 {ratio:.0%}，有可能存在内容丢失风险，请对报告内容进行检查并采取合理的行动。\n'
             '**重要提醒**：draft.md 是由工具逐章组装的完整版本，理论上保留了最大的证据保真度。\n'
             '- 如果你确认你对 draft.md 进行的修改是合理的，可以直接说明压缩内容的理由，无需再次修改或者重写。\n'
             '- 如果你发现 reports/{report_name} 相比 draft.md 确实存在不合理的压缩，请通过重写/追加/续写等方式来修复这些问题。\n'
             '请立即采取行动完成报告交付。'),
            'low_quality':
            ('外部检查发现：报告内容存在质量问题——{reason}。\n'
             '请仔细确认上述质量问题是否属实、是否还有更多问题，并立即采取行动修复。\n'
             '**重要提醒**：如果质量问题属实，你必须完整重写整份报告。'
             'write_file 会完全覆盖文件，你写入的内容就是最终文件的全部内容——'
             '以下写法都会原样出现在文件中并导致报告内容被永久丢失：\n'
             '- 用省略号或缩略标记替代正文，如"（同之前，略）"、"此处省略"、"篇幅所限不再展开"、'
             '"……以下类似"、"内容已截断"、"Content truncated for brevity"等；\n'
             '- 引导读者查看外部文件而非包含实际内容，如"该部分内容保存在xxx文件中"等；\n'
             '- 引导读者查看引用来源而没有撰写实质性内容，如"详见[1]"等。\n'
             '不得遗漏或省略任何章节，无需担心与先前输出的内容或写入过的文件重复。'),
        },
        'en': {
            'no_report':
            ('External inspection found that the completed report file reports/report.md '
             'has not been detected in the output directory.\n'
             'Please confirm whether the report writing workflow has been completed. '
             'You should have completed at least the following steps:\n'
             '1. Finished writing all chapters\n'
             '2. Called report_generator---assemble_draft to generate the report draft\n'
             '3. Reviewed the draft and delivered the final version\n'
             'Please take immediate action to complete report delivery.'),
            'over_compressed':
            ('External inspection found that reports/{report_name} ({report_chars} chars) '
             'is only {ratio:.0%} of reports/draft.md ({draft_chars} chars), '
             'indicating a risk of content loss. Please review the report content and take appropriate action.\n'
             '**IMPORTANT**: draft.md is the tool-assembled complete version that theoretically '
             'preserves maximum evidence fidelity.\n'
             '- If you confirm that your modifications to draft.md are reasonable, you may simply '
             'explain the rationale for the compression without further modifications or rewrites.\n'
             '- If you find that reports/{report_name} has indeed been unreasonably compressed '
             'compared to draft.md, please rewrite/append/continue writing to repair these issues.\n'
             'Please take immediate action to complete report delivery.'),
            'low_quality':
            ('External inspection found quality issues in the report — {reason}.\n'
             'Please carefully verify whether these issues are valid and whether additional '
             'problems exist, then immediately take action to fix them.\n'
             '**IMPORTANT**: If the quality issues are confirmed, you must completely rewrite '
             'the entire report. write_file will fully overwrite the file — what you write is '
             'the entire final content of the file. The following patterns will appear verbatim '
             'in the file and cause permanent loss of report content:\n'
             '- Replacing body text with ellipsis or brevity markers, e.g., "(same as before, omitted)", '
             '"omitted here", "not elaborated due to space constraints", '
             '"...similar below", "content truncated", "Content truncated for brevity", etc.;\n'
             '- Directing readers to view external files instead of including actual content, '
             'e.g., "this section is stored in xxx file", etc.;\n'
             '- Directing readers to view reference sources without writing substantive content, '
             'e.g., "see [1]", etc.\n'
             'Do not omit or skip any sections. Do not worry about duplicating content '
             'from previous outputs or previously written files.'),
        },
    }

    _POST_REPORT_GUIDANCE = {
        'zh':
        ('\n\n---\n'
         '**[后续工作流程建议]**\n\n'
         'Reporter 已完成报告生成。如果其正常返回工作总结，请仔细审阅返回内容的 Execution_Summary 和 Artifacts 字段，'
         '它们总结了报告生成过程并列出了重要的中间文件产物。如果其未正常完成任务或者未正常返回信息，请主动检查 reports 目录下的产物情况确定后续行动。\n\n'
         '**关于 final_report.md：'
         '** 上方 Artifacts 字段通常只包含 reports/ 目录下的文件（如 reports/report.md），'
         '不包含 final_report.md。这是正常的——系统会在 Reporter 正常完成任务后自动将 reports/report.md 复制为 final_report.md。'
         '你的审阅和编辑应优先针对 final_report.md。如有需要可按需读取 reports/ 下的其他文件作为参考，'
         '但当 final_report.md 可用时避免重复读取 reports/report.md。如果 final_report.md 意外缺失或不完整，按此路径回退：'
         'reports/report.md -> reports/draft.md -> reports/ 下其他产物内容。\n\n'
         '**审查与编辑注意事项：**\n'
         '- 请严格遵守系统指令中的要求，不要遗漏、忽略任何合理的规则。\n'
         '- 审查要点包括事实准确性、逻辑一致性、用户核心问题的覆盖度、引用与论据的对齐关系、引用格式问题、内容完整性等等。'
         '修改须有明确依据（如事实冗余、逻辑混乱、证据不一致、格式出错等），不要为了"润色"而改动结构/质量良好的内容。\n'
         '- 读取报告内容一次后形成判断，后续核查优先使用 read_file 的 offset/limit 或 abbreviate，不要反复全量读取同一文件。'
         '在读取文件前先检查对话历史中是否已包含该文件的内容，避免重复读取。\n'
         '- 优先使用定点修改（read_file 定位片段 -> edit_file 精确替换），仅在必要时才读取全文。'
         '仅在定点修改完全无法解决时使用 write_file，且**必须完整保留所有有价值的内容**，严禁使用占位符、省略标记、引用其他内容等方式替代正文。\n'
         '- 质量较高无需修改的部分直接跳过。如果[Reporter 工作总结]中无异常且审查确认全文质量良好，直接进入结论阶段即可。\n\n'
         '**需避免的常见错误：**\n'
         '- 重复全量读取同一个报告文件（迅速耗尽上下文预算，导致任务失败）。\n'
         '- 默认 final_report.md 不存在、且使用简短的概述内容覆盖完整报告。\n'
         '- 对结构/质量良好的内容过度修改或者压缩，或在修改过程中忘记已做的改动重复编辑导致错误。\n'),
        'en':
        ('\n\n---\n'
         '**[Post-Report Workflow Guidance]**\n\n'
         'The Reporter has finished generating the report. If it returned a work summary normally, '
         'please carefully review the Execution_Summary and Artifacts fields in the returned content — '
         'they summarize the report generation process and list important intermediate file artifacts. '
         'If Reporter did not complete the task normally or did not return information properly, '
         'proactively check the artifacts under the `reports/` directory to determine next steps.\n\n'
         '**About `final_report.md`:** The Artifacts field above typically lists only '
         'files under `reports/` (e.g., `reports/report.md`) and will NOT include '
         '`final_report.md`. This is expected — the system automatically copies '
         '`reports/report.md` to `final_report.md` after the Reporter finishes normally. '
         'Your review and edits should target `final_report.md`. You may read other '
         'files under `reports/` as supplementary references when needed, '
         'but avoid reading `reports/report.md` in full when '
         '`final_report.md` is available. If `final_report.md` is unexpectedly '
         'missing or incomplete, fall back in this order: '
         '`reports/report.md` -> `reports/draft.md` -> other artifacts under `reports/`.\n\n'
         '**Review and editing guidelines:**\n'
         '- Strictly follow the requirements in the system instructions; do not overlook or ignore any reasonable rules.\n'
         '- Key review points include factual accuracy, logical consistency, coverage of the user\'s core questions, '
         'alignment between citations and supporting arguments, citation formatting issues, content completeness, etc. '
         'Edits must have clear justification (e.g., factual redundancy, logical confusion, evidence inconsistency, '
         'formatting errors, etc.) — do not alter well-structured, high-quality content merely for "polishing."\n'
         '- Read the report content ONCE to form your assessment. For subsequent '
         'checks, prefer `read_file` with `offset`/`limit` or `abbreviate`. '
         'Do not re-read the entire file repeatedly. Check your conversation history before '
         'reading any file to avoid redundant reads.\n'
         '- Prefer targeted fixes (`read_file` to locate a span, then `edit_file` with exact '
         '`old_string`/`new_string`); only read the full text when necessary. '
         'Use `write_file` only when targeted fixes are completely insufficient, '
         'and you **must preserve ALL valuable content in full** — never use placeholders, '
         'ellipsis markers, or references to other content as substitutes for actual text.\n'
         '- Skip high-quality sections that require no changes. If the [Reporter Work Summary] '
         'indicates no issues and your review confirms overall quality, proceed '
         'directly to the conclusion.\n\n'
         '**Common mistakes to avoid:**\n'
         '- Reading the same report file in full multiple times (rapidly exhausts '
         'context budget and causes task failure).\n'
         '- Assuming `final_report.md` does not exist and overwriting the complete report '
         'with a brief summary.\n'
         '- Over-editing or compressing well-structured, high-quality content, or losing track '
         'of changes already made and making duplicate edits that introduce errors.\n'),
    }

    _WORK_SUMMARY_LABEL = {
        'zh': '**[Reporter 返回的 JSON 结果]**',
        'en': '**[Reporter\'s Returned JSON Result]**',
    }

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
                                        self.REPORT_FILENAME)
        self.draft_path = os.path.join(self.output_dir, self.reports_dir,
                                       self.DRAFT_FILENAME)
        self.final_report_path = os.path.join(self.output_dir,
                                              self.FINAL_REPORT_FILENAME)

        self.lang = self._resolve_lang(config)

        # Self-reflection config
        refl_cfg = getattr(config, 'self_reflection', None)
        self.reflection_enabled: bool = False
        self.reflection_max_retries: int = 2
        self.min_retention_ratio: float = self.DEFAULT_MIN_RETENTION_RATIO
        self.post_report_guidance_enabled: bool = False

        if refl_cfg is not None:
            self.reflection_enabled = bool(getattr(refl_cfg, 'enabled', False))
            self.reflection_max_retries = int(
                getattr(refl_cfg, 'max_retries', 2))
            self.min_retention_ratio = float(
                getattr(refl_cfg, 'min_retention_ratio',
                        self.DEFAULT_MIN_RETENTION_RATIO))
            self.post_report_guidance_enabled = bool(
                getattr(refl_cfg, 'post_report_guidance_enabled', False))

        self._reflection_retries_used: int = 0
        self._quality_checkers: List[ReportQualityChecker] = (
            build_quality_checkers(config))

    @staticmethod
    def _resolve_lang(config: DictConfig) -> str:
        """Resolve language code from config.prompt.lang, defaulting to 'en'."""
        prompt_cfg = getattr(config, 'prompt', None)
        if prompt_cfg is not None:
            lang = getattr(prompt_cfg, 'lang', None)
            if isinstance(lang, str) and lang.strip():
                normed = lang.strip().lower()
                if normed in {'en', 'en-us', 'en_us', 'us'}:
                    return 'en'
                elif normed in {'zh', 'zh-cn', 'zh_cn', 'cn'}:
                    return 'zh'
        return 'en'

    def _get_reflection(self, key: str, **kwargs) -> str:
        templates = self._REFLECTION_TEMPLATES.get(
            self.lang, self._REFLECTION_TEMPLATES['en'])
        return templates[key].format(**kwargs)

    def _append_post_report_guidance(self, messages: List[Message]):
        """Append post-report workflow guidance to the Reporter's final message.

        The guidance is appended to the last non-tool-call assistant message
        so that it appears as part of the tool result when the parent agent
        (Researcher) receives the Reporter's output via AgentTool.
        """
        guidance = self._POST_REPORT_GUIDANCE.get(
            self.lang, self._POST_REPORT_GUIDANCE['en'])
        label = self._WORK_SUMMARY_LABEL.get(
            self.lang, self._WORK_SUMMARY_LABEL['en'])
        for message in reversed(messages):
            if message.role == 'assistant' and not message.tool_calls:
                message.content = label + '\n\n' + (message.content or '') + guidance
                logger.info(
                    'ReporterCallback: appended post-report guidance '
                    f'to final assistant message ({len(guidance)} chars)')
                return
        logger.warning(
            'ReporterCallback: no suitable assistant message found '
            'for post-report guidance injection.')

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
        labels = self._TRAJECTORY_LABELS.get(self.lang,
                                             self._TRAJECTORY_LABELS['en'])
        lines = [labels['title'], '']

        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            tool_calls = msg.get('tool_calls') or []
            tool_name = msg.get('name', '')

            if role == 'user':
                lines.append(labels['user_request'])
                lines.append(content[:2000] if content else '(empty)')
                lines.append('')

            elif role == 'assistant':
                if content:
                    lines.append(labels['assistant_thinking'])
                    lines.append(
                        content[:20000] if len(content) > 20000 else content)
                    lines.append('')

                if tool_calls:
                    lines.append(labels['tool_calls'])
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
                lines.append(f'{labels["tool_result"]} ({tool_name})')
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

                labels = self._TRAJECTORY_LABELS.get(
                    self.lang, self._TRAJECTORY_LABELS['en'])
                trajectory_str = (f'{labels["trajectory_intro"]}\n\n'
                                  f'{trajectory_text}')

                if messages[insert_pos].role == 'user':
                    messages[insert_pos].content += f'\n\n{trajectory_str}'
                else:
                    # fallback: insert as a standalone message
                    messages.insert(
                        insert_pos,
                        Message(role='user', content=trajectory_str))

                logger.info(
                    f'Injected researcher trajectory ({len(trajectory_text)} chars) '
                    f'into reporter messages at position {insert_pos}')

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
            custom_message = self._ROUND_REMINDER_TEMPLATES.get(
                self.lang, self._ROUND_REMINDER_TEMPLATES['en'])

        injected = custom_message
        injected = injected.replace('<round>', str(runtime.round))
        injected = injected.replace('<max_chat_round>', str(max_chat_round))
        injected = injected.replace('<remaining_rounds>', str(remaining))
        messages.append(
            Message(role='user', content=reminder_mark + injected + '\n'))

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        """Pre-completion quality checks before allowing the reporter to stop.

        Checks performed (in order, first failure wins):
        1. Report file existence — report.md must exist.
        2. Length retention — if report.md exists alongside draft.md, its
           size must be >= ``min_retention_ratio`` of draft.md.
        3. Model quality audit — detects placeholder / abbreviated content.
        """
        if not self.reflection_enabled:
            return
        if not runtime.should_stop:
            return
        if self._reflection_retries_used >= self.reflection_max_retries:
            logger.info('ReporterCallback: reflection retry cap reached '
                        f'({self.reflection_max_retries}), allowing stop.')
            return

        has_report = os.path.isfile(self.report_path)
        has_draft = os.path.isfile(self.draft_path)

        # --- Check 1: report file existence ---
        if not has_report:
            logger.warning('ReporterCallback: no report found, '
                           'injecting reflection prompt.')
            prompt = self._get_reflection('no_report')
            messages.append(Message(role='user', content=prompt))
            runtime.should_stop = False
            self._reflection_retries_used += 1
            return

        # --- Check 2: length retention ---
        if has_report and has_draft:
            try:
                with open(self.report_path, 'r', encoding='utf-8') as f:
                    report_chars = len(f.read())
                with open(self.draft_path, 'r', encoding='utf-8') as f:
                    draft_chars = len(f.read())
                if draft_chars > 0:
                    ratio = report_chars / draft_chars
                    if ratio < self.min_retention_ratio:
                        logger.warning(f'ReporterCallback: report.md is only '
                                       f'{ratio:.0%} of draft.md, '
                                       'injecting over-compression prompt.')
                        prompt = self._get_reflection(
                            'over_compressed',
                            report_name=self.REPORT_FILENAME,
                            report_chars=report_chars,
                            draft_chars=draft_chars,
                            ratio=ratio)
                        messages.append(Message(role='user', content=prompt))
                        runtime.should_stop = False
                        self._reflection_retries_used += 1
                        return
            except OSError as exc:
                logger.warning(
                    f'ReporterCallback: failed to read report files: {exc}')

        # --- Check 3: quality checker chain ---
        if not self._quality_checkers:
            logger.info('ReporterCallback: no quality checkers configured, '
                        'skipping quality gate.')
            return

        try:
            with open(self.report_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as exc:
            logger.warning(f'ReporterCallback: failed to read report: {exc}')
            return

        for checker in self._quality_checkers:
            failure = await checker.check(content, self.lang)
            if failure is not None:
                logger.warning(f'ReporterCallback: quality check failed '
                               f'({type(checker).__name__}: {failure}), '
                               'injecting reflection prompt.')
                prompt = self._get_reflection('low_quality', reason=failure)
                messages.append(Message(role='user', content=prompt))
                runtime.should_stop = False
                self._reflection_retries_used += 1
                return

        logger.info('ReporterCallback: all pre-completion checks passed.')

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

    def _select_best_report(self) -> Optional[str]:
        """Return the path to the best available report file.

        Prefers ``report.md`` when it exists and passes the length
        retention check against ``draft.md``.  Falls back to
        ``draft.md`` otherwise.
        """
        has_report = os.path.isfile(self.report_path)
        has_draft = os.path.isfile(self.draft_path)

        if has_report and has_draft:
            try:
                with open(self.report_path, 'r', encoding='utf-8') as f:
                    report_chars = len(f.read())
                with open(self.draft_path, 'r', encoding='utf-8') as f:
                    draft_chars = len(f.read())
                if draft_chars > 0:
                    ratio = report_chars / draft_chars
                    if ratio < self.min_retention_ratio:
                        logger.warning(
                            f'ReporterCallback: report.md ({report_chars} '
                            f'chars) is only {ratio:.0%} of draft.md '
                            f'({draft_chars} chars). '
                            f'Using draft.md as final report source.')
                        return self.draft_path
            except OSError:
                pass
            return self.report_path
        elif has_report:
            return self.report_path
        elif has_draft:
            return self.draft_path
        return None

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """Promote the best report to final_report.md and save JSON summary."""

        # --- Step 1: Extract and save JSON summary from last message ---
        for message in reversed(messages):
            if message.role == 'assistant' and not message.tool_calls:
                content = message.content
                if not content:
                    continue

                json_result = self._extract_json_from_content(content)
                if json_result:
                    os.makedirs(
                        os.path.dirname(self.report_path), exist_ok=True)
                    json_path = self.report_path.replace('.md', '.json')
                    try:
                        with open(json_path, 'w', encoding='utf-8') as f:
                            json.dump(
                                json_result, f, ensure_ascii=False, indent=2)
                        logger.info(
                            f'Reporter: JSON result saved to {json_path}')
                    except Exception as exc:
                        logger.warning(f'Reporter: failed to save JSON: {exc}')
                break

        # --- Step 2: Promote best report to final_report.md ---
        best_source = self._select_best_report()
        if best_source:
            try:
                os.makedirs(
                    os.path.dirname(self.final_report_path), exist_ok=True)
                shutil.copy2(best_source, self.final_report_path)
                source_name = os.path.basename(best_source)
                logger.info(
                    f'Reporter: promoted {source_name} -> '
                    f'{self.FINAL_REPORT_FILENAME} '
                    f'({os.path.getsize(self.final_report_path)} bytes)')
            except Exception as exc:
                logger.warning(f'Reporter: failed to copy report to '
                               f'{self.final_report_path}: {exc}')
        else:
            logger.warning('Reporter: no report file found to promote to '
                           f'{self.FINAL_REPORT_FILENAME}')

        # --- Step 3: Append post-report workflow guidance ---
        if self.post_report_guidance_enabled:
            self._append_post_report_guidance(messages)
