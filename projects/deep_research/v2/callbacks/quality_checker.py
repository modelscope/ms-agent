# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import ABC, abstractmethod
from typing import List, Optional

import json
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
         '3. Sections that guide the reader to view the reference source instead of writing substantive content, e.g. "See [1]", "Reference [2]".\n'
         '4. Multiple reference/bibliography sections appear in the report (e.g., per-chapter reference lists), or any '
         'variant heading such as "## References (Merged)", "## 参考文献（合并版）", "## 参考资料", etc. '
         'Only one unified reference section at the very end is allowed.\n\n'
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
         '3. 正文引导读者查看引用来源而没有撰写实质性内容，如"详见[1]"、"参考[2]"。\n'
         '4. 报告中出现多个参考文献/引用列表章节（如各章节末尾的独立引用列表），或使用变体标题如"## 参考文献（合并版）"、"## 参考资料"、"## References (Merged)"等。'
         '报告仅允许在末尾保留唯一一个统一的参考文献章节。\n\n'
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


def build_quality_checkers(config: DictConfig) -> List[ReportQualityChecker]:
    """Instantiate the quality-checker chain from config.

    Reads ``config.self_reflection.quality_check`` and returns a list of
    checker instances.  Currently only ``ModelQualityChecker`` is
    supported; new checker types can be added here.
    """
    refl_cfg = getattr(config, 'self_reflection', None)
    if refl_cfg is None:
        return []

    qc_cfg = getattr(refl_cfg, 'quality_check', None)
    if qc_cfg is None or not bool(getattr(qc_cfg, 'enabled', False)):
        return []

    checkers: List[ReportQualityChecker] = []
    checkers.append(ModelQualityChecker(config))
    logger.info(
        f'Quality checker chain initialised with {len(checkers)} checker(s).')
    return checkers
