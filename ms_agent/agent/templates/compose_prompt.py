# Copyright (c) Alibaba, Inc. and its affiliates.
"""Compose a layered system prompt: a shared BASE + a per-template SPECIALIZATION.

A template declares::

    prompt:
      base: general        # general | worker | none (default: none)
      system: |            # specialization only
        <template-specific role / boundaries / workflow>

``compose_system_prompt`` reads ``prompts/base/<base>.md`` and prepends it to
``prompt.system``. Non-template configs (no ``prompt.base``) are untouched.

Environment placeholders in the base (``<current_date>`` / ``<cwd>`` / ``<os>``)
are filled at run time by ``StateInjectCallback`` (kept out of load-time so the
prompt text stays stable for caching across processes).
"""
from __future__ import annotations

from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent / 'prompts' / 'base'


def _base_path(name: str) -> Path:
    return _BASE_DIR / f'{name}.md'


def compose_system_prompt(config):
    """Prepend the selected base prompt to ``config.prompt.system``.

    Returns ``config`` unchanged when there is no ``prompt.base`` (or it is
    ``none`` / missing on disk). Best-effort: never raises.
    """
    prompt = getattr(config, 'prompt', None)
    if prompt is None:
        return config
    base_name = getattr(prompt, 'base', None)
    if not base_name or str(base_name).lower() == 'none':
        return config
    path = _base_path(str(base_name))
    if not path.is_file():
        return config
    base_text = path.read_text(encoding='utf-8').rstrip()
    spec = getattr(prompt, 'system', '') or ''
    spec = spec.strip()
    config.prompt.system = base_text + ('\n\n' + spec if spec else '')
    return config
