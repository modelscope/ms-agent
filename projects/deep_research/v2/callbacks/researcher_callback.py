# Copyright (c) Alibaba, Inc. and its affiliates.
# yapf: disable
import os
import re
import shutil
from typing import List, Optional

from callbacks.quality_checker import (ReportQualityChecker,
                                       build_quality_checkers)
from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.openai_llm import OpenAI as OpenAILLM
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig, OmegaConf

logger = get_logger()


class ResearcherCallback(Callback):
    """Callback for Researcher agent — pre-completion self-reflection.

    Intercepts the agent's stop decision in ``after_tool_call`` and runs
    a chain of quality checks before allowing the run to end:

    1. **File existence**: has ``final_report.md`` been written to disk?
    2. **Compression check**: is the report over-compressed vs
       ``reports/draft.md``?
    3. **Quality checkers**: a configurable list of
       :class:`ReportQualityChecker` instances run in order; the first
       failure triggers a reflection prompt.

    At task end (``on_task_end``), optionally:

    - Selects the best available report source (``final_report.md`` >
      ``reports/report.md`` > ``reports/draft.md``) based on character-count
      retention ratio, and promotes it to ``final_report.md``.
    - Runs a format-cleanup agent to fix citation and reference formatting
      issues (e.g., multiple reference sections, inconsistent numbering).

    YAML configuration (all optional, shown with defaults)::

        self_reflection:
          enabled: true
          max_retries: 2
          report_filename: final_report.md
          compression_check:
            enabled: false
            min_retention_ratio: 0.3
          report_selection:
            enabled: false
            min_retention_ratio: 0.3
          report_cleanup:
            enabled: false
            # model: ...          # defaults to researcher llm.model
            # openai_api_key: ... # falls back to llm.openai_api_key
            # openai_base_url: ... # falls back to llm.openai_base_url
          quality_check:
            enabled: true
            model: qwen3.5-flash          # lightweight audit model
            # openai_api_key: ...          # falls back to llm.openai_api_key
            # openai_base_url: ...         # falls back to llm.openai_base_url
    """

    REPORTS_DIR = 'reports'
    DRAFT_FILENAME = 'draft.md'
    REPORT_FILENAME = 'report.md'
    DEFAULT_MIN_RETENTION_RATIO = 0.3
    _CLEANUP_OUTPUT_MIN_RATIO = 0.75
    _MAX_CLEANUP_CHARS = 200000

    _REFLECTION_TEMPLATES = {
        'zh': {
            'no_report':
            ('外部检查发现：输出目录中尚未生成 {filename}，该文件原本应由 Reporter 子代理自动创建。\n'
             '请确认最终报告未交付的原因，并立即采取行动修复。\n'
             '请注意：不要使用占位符或缩略内容替代实际报告正文。'),
            'over_compressed':
            ('外部检查发现：{report_name} 的内容量（{report_chars} 字符）'
             '仅为 {draft_name}（{draft_chars} 字符）的 {ratio:.0%}，有可能存在内容丢失风险，'
             '请对报告内容进行检查并采取合理的行动。\n'
             '**重要提醒**：{draft_name} 是由工具逐章组装的完整版本，理论上保留了最大的证据保真度。\n'
             '- 如果你确认你对报告进行的修改是合理的，可以直接说明压缩内容的理由，无需再次修改或者重写。\n'
             '- 如果你发现 {report_name} 相比 {draft_name} 确实存在不合理的压缩，'
             '请通过重写/追加/续写等方式来修复这些问题。\n'
             '请立即采取行动完成报告交付。'),
            'low_quality':
            ('外部检查发现：{filename} 的内容存在质量问题——{reason}。\n'
             '请仔细确认上述质量问题是否属实、是否还有更多问题，并立即采取行动修复。\n'
             '**重要提醒**：如果质量问题属实，你必须按照以下原则进行修复：\n'
             '1. 优先通过有针对性的局部修改完成修复。请使用 file_system---search_file_content 定位问题段落，'
             '然后使用 file_system---replace_file_contents 和 file_system---replace_file_lines 进行针对性修复。'
             '需要时可以使用 file_system---read_file (with start_line/end_line) 验证上下文是否一致。\n'
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
            'over_compressed':
            ('External inspection found that {report_name} ({report_chars} chars) '
             'is only {ratio:.0%} of {draft_name} ({draft_chars} chars), '
             'indicating a risk of content loss. Please review the report content and take appropriate action.\n'
             '**IMPORTANT**: {draft_name} is the tool-assembled complete version that theoretically '
             'preserves maximum evidence fidelity.\n'
             '- If you confirm that your modifications to the report are reasonable, you may simply '
             'explain the rationale for the compression without further modifications or rewrites.\n'
             '- If you find that {report_name} has indeed been unreasonably compressed '
             'compared to {draft_name}, please rewrite/append/continue writing to repair these issues.\n'
             'Please take immediate action to complete report delivery.'),
            'low_quality':
            ('External inspection found quality issues in {filename} — {reason}.\n'
             'Please carefully verify whether these issues are valid and whether additional problems exist, '
             'then immediately take action to fix them.\n'
             '**IMPORTANT**: If the quality issues are confirmed, you must follow these principles to fix them:\n'
             '1. PREFER targeted, localized fixes. Use file_system---search_file_content to locate the problematic sections, '
             'then use file_system---replace_file_contents and file_system---replace_file_lines to apply precise corrections. '
             'use file_system---read_file (with start_line/end_line) to verify surrounding context when needed.\n'
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

    _CLEANUP_SYSTEM_PROMPTS = {
        'zh':
        ('你是一个研究报告格式清理专家。你的唯一任务是修复报告中的引用和参考文献格式问题。'
         '你绝对不能修改报告的实质内容、论点、证据或分析。\n\n'
         '只修复以下类型的问题：\n'
         '1. 多个参考文献章节：将所有分散的参考文献列表合并为报告末尾的唯一一个统一参考文献章节。'
         '移除完全重复的参考文献条目，按首次出现顺序重新编号。\n'
         '2. 引用标记不一致：确保正文中所有引用标记使用统一格式（如 [1], [2]），修复格式错误的引用标记。\n'
         '3. 失效引用：修复引用了不存在条目的标记，或处理从未被引用的参考文献条目。\n'
         '4. 参考文献编号：确保参考文献按照在正文中首次出现的顺序从 [1] 开始连续编号。\n'
         '5. 参考文献格式：确保每条参考文献遵循一致的格式。\n\n'
         '关键规则：\n'
         '- 不得修改、增加、删除或改写任何实质性内容。\n'
         '- 不得改变标题、章节结构或组织方式（合并参考文献章节除外）。\n'
         '- 不得添加新的引用或删除已引用的内容。\n'
         '- 如果报告没有格式问题，则原样返回。\n'
         '- 返回修复后的完整报告，而不仅仅是修改的部分。\n'
         '- 不要使用 markdown 代码块包裹输出。'),
        'en':
        ('You are a research report formatting specialist. Your ONLY job is to fix citation '
         'and reference formatting issues in the report. You must NOT modify the substantive '
         'content, arguments, evidence, or analysis in any way.\n\n'
         'Fix ONLY the following types of issues:\n'
         '1. Multiple reference sections: Merge all scattered reference/bibliography lists into '
         'a single unified reference section at the very end of the report. Remove exact duplicate '
         'entries and renumber sequentially by order of first appearance.\n'
         '2. Citation marker inconsistencies: Ensure all in-text citation markers use a consistent '
         'format (e.g., [1], [2]) throughout the report. Fix any malformed citation markers.\n'
         '3. Orphaned citations: Fix citation markers that reference non-existent entries, or handle '
         'reference entries that are never cited in the text.\n'
         '4. Reference numbering: Ensure references are numbered sequentially starting from [1], '
         'in order of first appearance in the text.\n'
         '5. Reference entry formatting: Ensure each reference entry follows a consistent format.\n\n'
         'CRITICAL RULES:\n'
         '- Do NOT modify, add, remove, or rephrase any substantive content.\n'
         '- Do NOT change headings, section structure, or organization (except merging reference sections).\n'
         '- Do NOT add new citations or remove existing cited content.\n'
         '- If the report has no formatting issues, return it unchanged.\n'
         '- Return the COMPLETE report with fixes applied, not just the changed parts.\n'
         '- Do NOT wrap the output in markdown code blocks.'),
    }

    _CLEANUP_USER_TEMPLATES = {
        'zh': ('请修复以下研究报告中的引用和参考文献格式问题：\n\n'
               '---报告开始---\n{report}\n---报告结束---'),
        'en': ('Please fix the citation and reference formatting issues '
               'in the following research report:\n\n'
               '---BEGIN REPORT---\n{report}\n---END REPORT---'),
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

        # --- Compression check config ---
        comp_cfg = (
            getattr(refl_cfg, 'compression_check', None) if refl_cfg else None)
        self.compression_check_enabled: bool = False
        self.min_retention_ratio: float = self.DEFAULT_MIN_RETENTION_RATIO
        if comp_cfg is not None:
            self.compression_check_enabled = bool(
                getattr(comp_cfg, 'enabled', False))
            self.min_retention_ratio = float(
                getattr(comp_cfg, 'min_retention_ratio',
                        self.DEFAULT_MIN_RETENTION_RATIO))

        # --- Report selection config (on_task_end) ---
        sel_cfg = (
            getattr(refl_cfg, 'report_selection', None) if refl_cfg else None)
        self.report_selection_enabled: bool = False
        self._selection_min_ratio: float = self.DEFAULT_MIN_RETENTION_RATIO
        if sel_cfg is not None:
            self.report_selection_enabled = bool(
                getattr(sel_cfg, 'enabled', False))
            self._selection_min_ratio = float(
                getattr(sel_cfg, 'min_retention_ratio',
                        self.DEFAULT_MIN_RETENTION_RATIO))

        # --- Format cleanup agent config (on_task_end) ---
        cleanup_cfg = (
            getattr(refl_cfg, 'report_cleanup', None) if refl_cfg else None)
        self.report_cleanup_enabled: bool = False
        self._cleanup_model: Optional[str] = None
        self._cleanup_api_key: Optional[str] = None
        self._cleanup_base_url: Optional[str] = None
        self._cleanup_generation_config: Optional[dict] = None
        if cleanup_cfg is not None:
            self.report_cleanup_enabled = bool(
                getattr(cleanup_cfg, 'enabled', False))
            self._cleanup_model = getattr(cleanup_cfg, 'model', None)
            self._cleanup_api_key = getattr(cleanup_cfg, 'openai_api_key',
                                            None)
            self._cleanup_base_url = getattr(cleanup_cfg, 'openai_base_url',
                                             None)
            gen_cfg = getattr(cleanup_cfg, 'generation_config', None)
            if gen_cfg is not None:
                self._cleanup_generation_config = (
                    OmegaConf.to_container(gen_cfg, resolve=True)
                    if isinstance(gen_cfg, DictConfig) else dict(gen_cfg))

        # --- Derived paths ---
        self._reports_dir: str = self.REPORTS_DIR
        self._draft_path: str = os.path.join(self.output_dir,
                                             self._reports_dir,
                                             self.DRAFT_FILENAME)
        self._inner_report_path: str = os.path.join(self.output_dir,
                                                    self._reports_dir,
                                                    self.REPORT_FILENAME)

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

    def _select_best_report(self) -> Optional[str]:
        """Return the path to the best available report, based on char-count
        retention ratio against ``reports/draft.md``.

        Candidates (in preference order):
        1. ``final_report.md``
        2. ``reports/report.md``
        3. ``reports/draft.md``

        A candidate is accepted if it has >= ``_selection_min_ratio`` chars
        relative to the draft.  Falls back to ``draft.md`` if all others
        are over-compressed.
        """
        final_path = self._report_path
        candidates = [
            (final_path, self.report_filename),
            (self._inner_report_path,
             os.path.join(self._reports_dir, self.REPORT_FILENAME)),
        ]

        has_draft = os.path.isfile(self._draft_path)
        if not has_draft:
            for path, _ in candidates:
                if os.path.isfile(path):
                    return path
            return None

        try:
            draft_chars = self._read_char_count(self._draft_path)
        except OSError:
            draft_chars = 0

        if draft_chars <= 0:
            for path, _ in candidates:
                if os.path.isfile(path):
                    return path
            return self._draft_path

        for path, name in candidates:
            if not os.path.isfile(path):
                continue
            try:
                chars = self._read_char_count(path)
            except OSError:
                continue
            ratio = chars / draft_chars
            if ratio >= self._selection_min_ratio:
                return path
            logger.warning(
                f'ResearcherCallback: {name} ({chars} chars) is only '
                f'{ratio:.0%} of draft ({draft_chars} chars), '
                f'trying next candidate.')

        logger.warning('ResearcherCallback: all candidates over-compressed, '
                       'falling back to draft.md.')
        return self._draft_path

    def _run_format_cleanup(self, report_path: str) -> bool:
        """Run format cleanup on the report to fix citation/reference issues.

        Returns True if cleanup was applied successfully.
        """
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as exc:
            logger.warning(f'ResearcherCallback: failed to read report for '
                           f'format cleanup: {exc}')
            return False

        if not content.strip():
            logger.info(
                'ResearcherCallback: report is empty, skipping cleanup.')
            return False

        if len(content) > self._MAX_CLEANUP_CHARS:
            logger.warning(
                f'ResearcherCallback: report too long for format cleanup '
                f'({len(content)} chars > {self._MAX_CLEANUP_CHARS}), '
                f'skipping.')
            return False

        model = (
            self._cleanup_model or getattr(self.config.llm, 'model', None))
        api_key = (
            self._cleanup_api_key
            or getattr(self.config.llm, 'openai_api_key', None))
        base_url = (
            self._cleanup_base_url
            or getattr(self.config.llm, 'openai_base_url', None))

        if not model:
            logger.warning(
                'ResearcherCallback: no model configured for format cleanup.')
            return False

        gen_cfg = self._cleanup_generation_config or {}
        llm_config = OmegaConf.create({
            'llm': {
                'model': model,
                'openai_api_key': api_key,
                'openai_base_url': base_url,
            },
            'generation_config': gen_cfg,
        })

        try:
            client = OpenAILLM(llm_config)
        except Exception as exc:
            logger.warning(f'ResearcherCallback: failed to create LLM client '
                           f'for format cleanup: {exc}')
            return False

        sys_prompt = self._CLEANUP_SYSTEM_PROMPTS.get(
            self.lang, self._CLEANUP_SYSTEM_PROMPTS['en'])
        usr_template = self._CLEANUP_USER_TEMPLATES.get(
            self.lang, self._CLEANUP_USER_TEMPLATES['en'])

        try:
            response = client.generate(messages=[
                Message(role='system', content=sys_prompt),
                Message(
                    role='user', content=usr_template.format(report=content)),
            ])
            cleaned = (response.content or '').strip()
        except Exception as exc:
            logger.warning(
                f'ResearcherCallback: format cleanup LLM call failed: {exc}')
            return False

        if not cleaned:
            logger.warning(
                'ResearcherCallback: format cleanup returned empty output.')
            return False

        # Strip markdown code-block wrapper if present
        cleaned = re.sub(r'^```\w*\n', '', cleaned)
        cleaned = re.sub(r'\n```\s*$', '', cleaned)

        # Guard against truncated output
        if len(cleaned) < len(content) * self._CLEANUP_OUTPUT_MIN_RATIO:
            logger.warning(
                f'ResearcherCallback: format cleanup output appears '
                f'truncated ({len(cleaned)} vs {len(content)} chars), '
                f'keeping original.')
            return False

        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            logger.info(f'ResearcherCallback: format cleanup applied '
                        f'({len(content)} -> {len(cleaned)} chars).')
            return True
        except Exception as exc:
            logger.warning(
                f'ResearcherCallback: failed to write cleaned report: {exc}')
            return False

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        # --- Step 1: Write task-finished marker ---
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

        # --- Step 2: Best report selection ---
        if self.report_selection_enabled:
            best_source = self._select_best_report()
            if best_source and best_source != self._report_path:
                try:
                    os.makedirs(
                        os.path.dirname(self._report_path), exist_ok=True)
                    shutil.copy2(best_source, self._report_path)
                    source_name = os.path.relpath(best_source, self.output_dir)
                    logger.info(
                        f'ResearcherCallback: promoted {source_name} -> '
                        f'{self.report_filename}')
                except Exception as exc:
                    logger.warning(
                        f'ResearcherCallback: failed to promote report: '
                        f'{exc}')
            elif best_source:
                logger.info(
                    f'ResearcherCallback: {self.report_filename} is already '
                    f'the best candidate, no promotion needed.')
            else:
                logger.warning('ResearcherCallback: no report file found for '
                               'best-report selection.')

        # --- Step 3: Format cleanup agent ---
        if self.report_cleanup_enabled:
            if os.path.isfile(self._report_path):
                logger.info(
                    'ResearcherCallback: running format cleanup agent on '
                    f'{self.report_filename}...')
                self._run_format_cleanup(self._report_path)
            else:
                logger.warning(
                    f'ResearcherCallback: {self.report_filename} not found, '
                    f'skipping format cleanup.')

    @staticmethod
    def _read_char_count(path: str) -> int:
        with open(path, 'r', encoding='utf-8') as f:
            return len(f.read())

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

        # --- Check 2: compression check vs reports/draft.md ---
        if self.compression_check_enabled and os.path.isfile(self._draft_path):
            try:
                report_chars = self._read_char_count(self._report_path)
                draft_chars = self._read_char_count(self._draft_path)
                if draft_chars > 0:
                    ratio = report_chars / draft_chars
                    if ratio < self.min_retention_ratio:
                        draft_rel = os.path.join(self._reports_dir,
                                                 self.DRAFT_FILENAME)
                        logger.warning(
                            f'ResearcherCallback: {self.report_filename} '
                            f'({report_chars} chars) is only {ratio:.0%} of '
                            f'{draft_rel} ({draft_chars} chars), '
                            'injecting over-compression prompt.')
                        prompt = self._get_template('over_compressed').format(
                            report_name=self.report_filename,
                            report_chars=report_chars,
                            draft_name=draft_rel,
                            draft_chars=draft_chars,
                            ratio=ratio)
                        messages.append(Message(role='user', content=prompt))
                        runtime.should_stop = False
                        self._retries_used += 1
                        return
            except OSError as exc:
                logger.warning(f'ResearcherCallback: failed to read files for '
                               f'compression check: {exc}')

        # --- Check 3: quality checker chain ---
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
