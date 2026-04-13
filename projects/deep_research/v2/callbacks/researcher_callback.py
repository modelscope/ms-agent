# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from typing import List, Optional

from callbacks.quality_checker import (ReportQualityChecker,
                                       build_quality_checkers)
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

logger = get_logger()


class ResearcherCallback(Callback):
    """Callback for Researcher agent — pre-completion self-reflection.

    Intercepts the agent's stop decision in ``after_tool_call`` and runs
    a chain of quality checks before allowing the run to end:

    1. **File existence**: has ``final_report.md`` been written to disk?
    2. **Quality checkers**: a configurable list of
       :class:`ReportQualityChecker` instances run in order; the first
       failure triggers a reflection prompt.

    If any check fails, a reflection prompt is injected as a ``user``
    message, ``runtime.should_stop`` is flipped back to ``False``, and
    the agent continues for one more iteration.  A configurable retry
    cap prevents infinite loops.

    YAML configuration (all optional, shown with defaults)::

        self_reflection:
          enabled: true
          max_retries: 2
          report_filename: final_report.md
          quality_check:
            enabled: true
            model: qwen3.5-flash          # lightweight audit model
            # openai_api_key: ...          # falls back to llm.openai_api_key
            # openai_base_url: ...         # falls back to llm.openai_base_url
    """

    _REFLECTION_TEMPLATES = {
        'zh': {
            'no_report':
            ('外部检查发现：输出目录中尚未生成 {filename}，该文件原本应由 Reporter 子代理自动创建。\n'
             '请确认最终报告未交付的原因，并立即采取行动修复。\n'
             '请注意：不要使用占位符或缩略内容替代实际报告正文。'),
            'low_quality':
            ('外部检查发现：{filename} 的内容存在质量问题——{reason}。\n'
             '请仔细确认上述质量问题是否属实、是否还有更多问题，并立即采取行动修复。\n'
             '**重要提醒**：如果质量问题属实，你必须按照以下原则进行修复：\n'
             '1. 优先通过有针对性的局部修改完成修复。请使用 file_system---read_file（可用 offset/limit 或 abbreviate）定位问题段落，'
             '然后使用 file_system---edit_file（old_string/new_string 必须与原文完全一致）进行针对性修复。'
             '需要时可以使用 file_system---read_file（with offset/limit）验证上下文是否一致。\n'
             '2. 如果确认无法通过1完成修复，可以使用 file_system---write_file 全量重写报告，但请注意以下可能的质量违规：\n'
             '- 用省略号或缩略标记替代正文，如"（同之前，略）"、"此处省略"、"篇幅所限不再展开"、'
             '"……以下类似"、"内容已截断"、"Content truncated for brevity"等；\n'
             '- 引导读者查看外部文件而非包含实际内容，如"该部分内容保存在xxx文件中"、'
             '"完整内容如 xxx 所述"、"详见附件"等；\n'
             '- 引导读者查看引用来源而没有撰写实质性内容，如"详见[1]"、"参考[2]"。\n'),
        },
        'en': {
            'no_report':
            ('External inspection found that {filename} has not yet been generated in the output directory; '
             'this file was expected to be created automatically by the Reporter sub-agent.\n'
             'Please identify why the final report was not delivered and immediately take action to fix it.\n'
             'Note: Do not use placeholders or abbreviated content in place of the actual report body.'
             ),
            'low_quality':
            ('External inspection found quality issues in {filename} — {reason}.\n'
             'Please carefully verify whether these issues are valid and whether additional problems exist, '
             'then immediately take action to fix them.\n'
             '**IMPORTANT**: If the quality issues are confirmed, you must follow these principles to fix them:\n'
             '1. PREFER targeted, localized fixes. Use file_system---read_file (with offset/limit or abbreviate) to locate the problematic sections, '
             'then use file_system---edit_file (exact old_string/new_string) to apply precise corrections. '
             'Use file_system---read_file (with offset/limit) to verify surrounding context when needed.\n'
             '2. If you confirm that targeted fixes alone cannot resolve the issues, you may use file_system---write_file '
             'to fully rewrite the report, but beware of the following quality violations:\n'
             '- Replacing body text with ellipsis or brevity markers, e.g., "(same as before, omitted)", '
             '"omitted here", "not elaborated due to space constraints", '
             '"...similar below", "content truncated", "Content truncated for brevity", etc.;\n'
             '- Directing readers to view external files instead of including actual content, e.g., '
             '"This section is stored in xxx file", "See full content in xxx", "See attachment", etc.;\n'
             '- Directing readers to view reference sources without writing substantive content, '
             'e.g., "See [1]", "Reference [2]".\n'),
        },
    }

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.output_dir: str = getattr(config, 'output_dir', './output')
        self.lang: str = self._resolve_lang(config)

        refl_cfg = getattr(config, 'self_reflection', None)
        self.enabled: bool = True
        self.max_retries: int = 2
        self.report_filename: str = 'final_report.md'

        if refl_cfg is not None:
            self.enabled = bool(getattr(refl_cfg, 'enabled', True))
            self.max_retries = int(getattr(refl_cfg, 'max_retries', 2))
            self.report_filename = str(
                getattr(refl_cfg, 'report_filename', self.report_filename))

        self._retries_used: int = 0
        self._checkers: List[ReportQualityChecker] = build_quality_checkers(
            config)

    @staticmethod
    def _resolve_lang(config: DictConfig) -> str:
        prompt_cfg = getattr(config, 'prompt', None)
        if prompt_cfg is not None:
            lang = getattr(prompt_cfg, 'lang', None)
            if isinstance(lang, str) and lang.strip():
                normed = lang.strip().lower()
                if normed in {'zh', 'zh-cn', 'zh_cn', 'cn'}:
                    return 'zh'
        return 'en'

    @property
    def _report_path(self) -> str:
        return os.path.join(self.output_dir, self.report_filename)

    def _get_template(self, key: str) -> str:
        templates = self._REFLECTION_TEMPLATES.get(
            self.lang, self._REFLECTION_TEMPLATES['en'])
        return templates[key]

    TASK_FINISHED_MARKER = '.researcher_task_finished'

    @property
    def _marker_path(self) -> str:
        return os.path.join(self.output_dir, self.TASK_FINISHED_MARKER)

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            with open(self._marker_path, 'w') as f:
                f.write('')
            logger.info(
                f'ResearcherCallback: wrote researcher_task_finished marker '
                f'at {self._marker_path}')
        except Exception as exc:
            logger.warning(
                f'ResearcherCallback: failed to write marker: {exc}')

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        if not self.enabled:
            return
        if not runtime.should_stop:
            return
        if self._retries_used >= self.max_retries:
            logger.info('ResearcherCallback: reflection retry cap reached '
                        f'({self.max_retries}), allowing stop.')
            return

        # --- Check 1: report file existence ---
        if not os.path.isfile(self._report_path):
            logger.warning(
                f'ResearcherCallback: {self.report_filename} not found, '
                'injecting reflection prompt.')
            prompt = self._get_template('no_report').format(
                filename=self.report_filename)
            messages.append(Message(role='user', content=prompt))
            runtime.should_stop = False
            self._retries_used += 1
            return

        # --- Check 2: quality checker chain ---
        if not self._checkers:
            logger.info('ResearcherCallback: no quality checkers configured, '
                        'skipping quality gate.')
            return

        try:
            with open(self._report_path, 'r', encoding='utf-8') as f:
                report_content = f.read()
        except Exception as exc:
            logger.warning(f'ResearcherCallback: failed to read report: {exc}')
            return

        for checker in self._checkers:
            failure = await checker.check(report_content, self.lang)
            if failure is not None:
                logger.warning(f'ResearcherCallback: quality check failed '
                               f'({type(checker).__name__}: {failure}), '
                               'injecting reflection prompt.')
                prompt = self._get_template('low_quality').format(
                    filename=self.report_filename, reason=failure)
                messages.append(Message(role='user', content=prompt))
                runtime.should_stop = False
                self._retries_used += 1
                return

        logger.info('ResearcherCallback: all pre-completion checks passed.')
