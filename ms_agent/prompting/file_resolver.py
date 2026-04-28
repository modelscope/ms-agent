# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from omegaconf import DictConfig


@dataclass(frozen=True)
class PromptFileSpec:
    agent: str
    lang: str
    family: str
    root_dir: str

    def candidate_paths(self) -> List[str]:
        """Return candidate prompt file paths in priority order."""
        # File convention: prompts/{agent}/{lang}/{family}.md
        # Fallback: family -> base
        agent = self.agent.strip()
        lang = self.lang.strip()
        family = self.family.strip()
        root = self.root_dir

        paths = []
        if family:
            paths.extend(
                [
                    os.path.join(root, agent, lang, f'{family}.txt'),
                    os.path.join(root, agent, lang, f'{family}.md'),
                ]
            )
        # base fallback
        paths.extend([os.path.join(root, agent, lang, 'base.txt'), os.path.join(root, agent, lang, 'base.md')])
        return paths


def _norm_lang(lang: Optional[str]) -> str:
    if not lang:
        return 'zh'
    lang = str(lang).strip().lower()
    if lang in {'zh', 'zh-cn', 'zh_cn', 'cn'}:
        return 'zh'
    if lang in {'en', 'en-us', 'en_us', 'us'}:
        return 'en'
    if lang == 'auto':
        # We cannot reliably detect user language at config-load time,
        # so treat "auto" as default language (with env override handled elsewhere).
        return 'zh'
    return lang


def _infer_family_from_model(model: Optional[str]) -> str:
    """Infer a reasonable prompt family name from model string.

    Notes:
    - This is a best-effort heuristic to keep user onboarding simple.
    - Users can always override via `prompt.family`.
    """
    if not model:
        return 'base'
    m = str(model).strip().lower()

    # Qwen series
    if 'qwen' in m:
        # Common variants: qwen3-*, qwen-3, qwen2.5-*, Qwen/Qwen3-...
        if 'qwen3' in m or 'qwen-3' in m or 'qwen/qwen3' in m:
            return 'qwen-3'
        if 'qwen2' in m or 'qwen-2' in m:
            return 'qwen-2'
        if 'qwen1' in m or 'qwen-1' in m:
            return 'qwen-1'
        return 'qwen'

    # Claude series
    if 'claude' in m:
        return 'claude'

    # GPT-like series (OpenAI / compatible)
    if 'gpt' in m or m.startswith('o1') or m.startswith('o3'):
        return 'gpt'

    return 'base'


def _get_prompt_root_dir(config: DictConfig) -> Optional[str]:
    """Resolve prompts root directory.

    Priority:
    - config.prompt.root (absolute or relative to config.local_dir)
    - <config.local_dir>/prompts
    """
    local_dir = getattr(config, 'local_dir', None)
    prompt_cfg = getattr(config, 'prompt', None)
    root = None
    if isinstance(prompt_cfg, DictConfig):
        root = getattr(prompt_cfg, 'root', None)

    if root:
        root = str(root).strip()
        if not root:
            root = None
        elif not os.path.isabs(root) and local_dir:
            root = os.path.join(str(local_dir), root)

    if not root and local_dir:
        root = os.path.join(str(local_dir), 'prompts')

    return root


def _get_prompt_agent(config: DictConfig) -> Optional[str]:
    """Resolve agent name used in prompts/{agent}/... path."""
    prompt_cfg = getattr(config, 'prompt', None)
    if isinstance(prompt_cfg, DictConfig):
        agent = getattr(prompt_cfg, 'agent', None)
        if agent:
            agent = str(agent).strip()
            if agent:
                return agent

    # Prefer `code_file` for project agents (deep_research v2 uses this)
    code_file = getattr(config, 'code_file', None)
    if code_file:
        code_file = str(code_file).strip()
        if code_file:
            return code_file

    # Fallback: try `tag` (may be too specific; we only use it if user opts in via prompt.agent)
    return None


def _get_prompt_lang_and_family(config: DictConfig) -> Tuple[str, str]:
    prompt_cfg = getattr(config, 'prompt', None)

    # lang
    env_lang = os.environ.get('MS_AGENT_PROMPT_LANG') or os.environ.get('MS_AGENT_LANG')
    cfg_lang = getattr(prompt_cfg, 'lang', None) if isinstance(prompt_cfg, DictConfig) else None
    lang = _norm_lang(cfg_lang or env_lang or 'zh')

    # family
    env_family = os.environ.get('MS_AGENT_PROMPT_FAMILY')
    cfg_family = getattr(prompt_cfg, 'family', None) if isinstance(prompt_cfg, DictConfig) else None

    family = cfg_family or env_family or 'auto'
    family = str(family).strip()
    if not family:
        family = 'auto'
    if family.lower() == 'auto':
        model = None
        if hasattr(config, 'llm') and getattr(config, 'llm') is not None:
            try:
                model = getattr(config.llm, 'model', None)
            except Exception:
                model = None
        family = _infer_family_from_model(model)
    return lang, family


def resolve_prompt_file(config: DictConfig) -> Optional[str]:
    """Resolve system prompt text from prompt files.

    Returns:
        Prompt text if a file is found, else None.

    Compatibility rules:
    - If `prompt.system` exists and is non-empty, this resolver is NOT used.
    - Resolver is only eligible when we can infer a prompt agent name (or user provided prompt.agent).
    """
    prompt_cfg = getattr(config, 'prompt', None)
    if isinstance(prompt_cfg, DictConfig):
        system = getattr(prompt_cfg, 'system', None)
        if isinstance(system, str) and system.strip():
            return None

    agent = _get_prompt_agent(config)
    if not agent:
        return None

    root_dir = _get_prompt_root_dir(config)
    if not root_dir:
        return None

    lang, family = _get_prompt_lang_and_family(config)

    # Language fallback: try configured lang first, then zh/en as last resort.
    lang_candidates = [lang]
    for fallback in ('zh', 'en'):
        if fallback not in lang_candidates:
            lang_candidates.append(fallback)

    for lang_try in lang_candidates:
        spec = PromptFileSpec(
            agent=agent,
            lang=lang_try,
            family=family,
            root_dir=root_dir,
        )
        for path in spec.candidate_paths():
            if os.path.isfile(path):
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
                text = text.strip('\n')
                return text if text.strip() else None

    return None


def apply_prompt_files(config: DictConfig) -> DictConfig:
    """Apply prompt file resolution onto config in-place.

    This sets `config.prompt.system` when it's missing/empty and a matching prompt file exists.
    """
    try:
        prompt_text = resolve_prompt_file(config)
    except Exception:
        # Be conservative: prompt loading must never break config loading.
        return config

    if not prompt_text:
        return config

    if not hasattr(config, 'prompt') or config.prompt is None:
        config.prompt = DictConfig({})
    if getattr(config.prompt, 'system', None) is None or not str(getattr(config.prompt, 'system', '')).strip():
        config.prompt.system = prompt_text
    return config
