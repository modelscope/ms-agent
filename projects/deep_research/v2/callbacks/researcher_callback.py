# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from abc import ABC, abstractmethod
from typing import List, Optional

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.openai_llm import OpenAI as OpenAILLM
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig, OmegaConf

logger = get_logger()


class ReportQualityChecker(ABC):
    """Interface for pluggable report quality checkers.

    Subclasses implement a single ``check`` method.  Multiple checkers can
    be chained in sequence by ``ResearcherCallback``; the first one that
    returns a non-``None`` failure stops the chain.
    """

    @abstractmethod
    async def check(self, content: str, lang: str) -> Optional[str]:
        """Evaluate report quality.

        Args:
            content: Full text of the report file.
            lang: Language code (``"en"`` or ``"zh"``).

        Returns:
            A short failure-reason string (e.g. ``"placeholder_content"``)
            if the report fails this check, or ``None`` if it passes.
        """


class ModelQualityChecker(ReportQualityChecker):
    """LLM-based report quality checker.

    Uses a lightweight model (configured via ``quality_check.model`` in
    the YAML) to detect reports whose body has been largely replaced by
    placeholders, abbreviations, or cross-references to external files.

    The checker sends a structured prompt asking the model to return a
    JSON verdict: ``{"pass": true/false, "reason": "..."}``.
    """

    _SYSTEM_PROMPTS = {
        'en':
        ('You are a strict report quality auditor. Your ONLY job is to detect whether a research report violates any of the rules listed below.\n'
         'You MUST check ONLY against these rules — do NOT invent additional criteria or penalize anything not explicitly listed here.\n'
         'If a problem is NOT described by rules below, you MUST ignore it and return {"pass": true}. '
         'Specifically: duplicate/repeated content, heading numbering gaps, structural ordering issues, stylistic choices, '
         'and the density of inline citations within otherwise substantive paragraphs are all OUT OF SCOPE and must NOT cause a failure.\n\n'
         'RULES — flag the report ONLY if ANY of the following are clearly found:\n'
         '1. Sections where detailed content has been replaced by ellipsis or brevity markers such as "...for brevity", '
         '"Content truncated for brevity", "omitted for brevity", "(remaining content follows the same pattern)", etc.\n'
         '2. Sections that refer the reader to an external file instead of containing actual content, e.g. "This section '
         'is stored in xxx file", "See full analysis in evidence/xxx".\n'
         '3. Sections that guide the reader to view the reference source instead of writing substantive content, e.g. "See [1]", "Reference [2]".\n\n'
         'OUTPUT FORMAT:\n'
         'Respond with EXACTLY one JSON object. No markdown fences, no explanation outside the JSON.\n'
         '{"pass": true} or {"pass": false, "reason": "<no more than three sentences; cite the exact rule number violated>"}\n'
         'Do NOT output anything else.'),
        'zh':
        ('你是一个严格的研究报告质量审核员，你唯一的任务是判断报告是否违反了下方列出的规则。\n'
         '你只能依据以下规则进行检查，不得自行发明额外标准，也不得基于规则未涉及的内容判定不通过。如果某个问题不属于下方规则的任何一条，你必须忽略它并返回 {"pass": true}。\n'
         '特别说明：重复/相似内容、标题编号跳跃、章节结构顺序问题、文体风格选择、以及在有实质论述的段落中密集使用行内引注，都不在检查范围内，不得因此判定不通过。\n\n'
         '规则 — 仅当明确发现以下任一问题时才判定不通过：\n'
         '1. 正文被省略号或缩略标记替代，如"此处省略"、"篇幅所限不再展开"、"……以下类似"、"内容已截断"、"...for brevity"、"omitted for brevity"等。\n'
         '2. 正文引导读者查看外部文件而非包含实际内容，如"该部分内容保存在xxx文件中"、"详见附件"、"See full analysis in evidence/xxx"。\n'
         '3. 正文引导读者查看引用来源而没有撰写实质性内容，如"详见[1]"、"参考[2]"。\n\n'
         '输出格式：\n'
         '只返回一个JSON对象，不要使用markdown代码块，不要在JSON之外输出任何文字。\n'
         '{"pass": true} 或者 {"reason": "<不得超过三句话；引用具体违反的规则编号>", "pass": false}\n'
         '不要输出任何其他内容。'),
    }

    _USER_TEMPLATES = {
        'en':
        ('Please audit the following research report against the rules provided in the system instruction.\n\n'
         '---BEGIN REPORT---\n{report}\n---END REPORT---'),
        'zh': ('请依据系统指令中提供的规则审核以下研究报告。\n\n'
               '---报告开始---\n{report}\n---报告结束---'),
    }

    _MAX_REPORT_CHARS = 80000

    def __init__(self, config: DictConfig):
        self._config = config
        qc_cfg = getattr(config, 'self_reflection', DictConfig({}))
        qc_cfg = getattr(qc_cfg, 'quality_check', DictConfig({}))

        self._model: str = str(getattr(qc_cfg, 'model', 'qwen3.5-plus'))
        self._api_key: Optional[str] = getattr(
            qc_cfg, 'openai_api_key', None) or getattr(config.llm,
                                                       'openai_api_key', None)
        self._base_url: Optional[str] = getattr(
            qc_cfg, 'openai_base_url', None) or getattr(
                config.llm, 'openai_base_url', None)

        self._client: Optional[OpenAILLM] = None

    def _build_llm_config(self) -> DictConfig:
        """Build lightweight llm config for quality checker."""
        return OmegaConf.create({
            'llm': {
                'model': self._model,
                'openai_api_key': self._api_key,
                'openai_base_url': self._base_url,
            },
            'generation_config': {},
        })

    def _ensure_client(self):
        if self._client is not None:
            return
        self._client = OpenAILLM(self._build_llm_config())

    async def check(self, content: str, lang: str) -> Optional[str]:
        import json

        self._ensure_client()

        report_text = content
        if len(report_text) > self._MAX_REPORT_CHARS:
            report_text = report_text[:self._MAX_REPORT_CHARS]

        sys_prompt = self._SYSTEM_PROMPTS.get(lang, self._SYSTEM_PROMPTS['en'])
        usr_template = self._USER_TEMPLATES.get(lang,
                                                self._USER_TEMPLATES['en'])

        try:
            response = self._client.generate(messages=[
                Message(role='system', content=sys_prompt),
                Message(
                    role='user',
                    content=usr_template.format(report=report_text),
                ),
            ])
            raw = (response.content or '').strip()
            logger.info(
                f'ModelQualityChecker ({self._model}): raw response: {raw}')

            verdict = json.loads(raw)
            if verdict.get('pass', True):
                return None
            return verdict.get('reason', 'placeholder_content')

        except json.JSONDecodeError:
            logger.warning(f'ModelQualityChecker: failed to parse JSON from '
                           f'model response: {raw!r}')
            return None
        except Exception as exc:
            logger.warning(f'ModelQualityChecker: model call failed: {exc}')
            return None


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
            'no_report': ('自查发现：输出目录中尚未生成 `{filename}`。\n'
                          '请确认最终报告未交付的原因，并立即采取行动修复。\n'
                          '请注意：不要使用占位符或缩略内容替代实际报告正文。'),
            'low_quality':
            ('外部检查发现：`{filename}` 的内容存在质量问题——{reason}。\n'
             '请仔细确认上述质量问题是否属实、是否还有更多问题，并立即采取行动修复。\n'
             '**重要提醒**：如果质量问题属实，你必须完整重写整份报告。'
             'write_file 会完全覆盖文件，你写入的内容就是最终文件的全部内容——'
             '以下写法都会原样出现在文件中并导致报告内容被永久丢失：\n'
             '- 用省略号或缩略标记替代正文，如"（同之前，略）"、"此处省略"、"篇幅所限不再展开"、'
             '"……以下类似"、"内容已截断"、"Content truncated for brevity"等；\n'
             '- 引导读者查看外部文件而非包含实际内容，如"该部分内容保存在xxx文件中"、'
             '"完整内容如 xxx 所述"、"详见附件"等；\n'
             '- 引导读者查看引用来源而没有撰写实质性内容，如"详见[1]"、"参考[2]"。\n'
             '不得遗漏或省略任何章节，无需担心与先前输出的内容或写入过的文件重复。'),
        },
        'en': {
            'no_report':
            ('Self-check indicates that `{filename}` has not yet been generated in the output directory.\n'
             'Please determine why the final report has not been delivered and take immediate action to fix the issue.\n'
             'Note: Do not use placeholders or abbreviated content in place of the actual report body.'
             ),
            'low_quality':
            ('External inspection found quality issues in `{filename}` — {reason}.\n'
             'Please carefully verify whether these issues are valid and whether additional problems exist, '
             'then immediately take action to fix them.\n'
             '**IMPORTANT REMINDER**: If the issues are valid, you MUST rewrite the complete report in full. '
             'write_file overwrites the entire file — what you write IS the final file content. '
             'The following patterns will appear literally in the file and permanently destroy report content:\n'
             '- Replacing substantive content with brevity markers, e.g., "(same as before, omitted)", '
             '"...for brevity", "Content truncated for brevity", "omitted for brevity", '
             '"(remaining content follows the same pattern)";\n'
             '- Referring readers to external files instead of including actual content, e.g., '
             '"This section is stored in xxx file", "See full analysis in evidence/xxx", '
             '"(see xxx for full content)";\n'
             '- Directing readers to view reference sources without writing substantive content, '
             'e.g., "See [1]", "Reference [2]".\n'
             'Do not omit or skip any sections; do not worry about repeating content you have previously output.'
             ),
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
        self._checkers: List[ReportQualityChecker] = self._build_checkers(
            config)

    @staticmethod
    def _build_checkers(config: DictConfig) -> List[ReportQualityChecker]:
        """Instantiate the quality-checker chain from config.

        Currently supports ``ModelQualityChecker``.  New checker types
        can be added here and will be appended to the chain — the first
        checker that returns a failure reason wins.
        """
        refl_cfg = getattr(config, 'self_reflection', None)
        if refl_cfg is None:
            return []

        qc_cfg = getattr(refl_cfg, 'quality_check', None)
        if qc_cfg is None or not bool(getattr(qc_cfg, 'enabled', False)):
            return []

        checkers: List[ReportQualityChecker] = []
        checkers.append(ModelQualityChecker(config))
        logger.info(f'ResearcherCallback: quality checker chain initialised '
                    f'with {len(checkers)} checker(s).')
        return checkers

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
