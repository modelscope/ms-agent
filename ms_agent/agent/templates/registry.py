# Copyright (c) Alibaba, Inc. and its affiliates.
"""Built-in template agent registry.

A *template* is an ordinary ms-agent config directory (``agent.yaml`` + optional
``prompts/``) that ships with the package and is resolvable by a bare name such
as ``general``, ``plan``, ``explore``, ``build`` or ``research``.

This module exposes two things:

1. ``resolve_template_source`` / ``resolve_template_dir`` -- name -> directory
   resolution, inserted into the existing config-loading seams (``Config.from_task``,
   ``AgentLoader.build``, the CLI). Local paths always win; unknown names fall
   through to the existing ModelScope resolution.
2. ``load_manifest`` / ``list_templates`` / ``get_when_to_use`` -- the template
   manifest (``registry.yaml``), used for CLI listing, WebUI selectors and
   sub-agent delegation description synthesis.

Resolution priority for a template name: project override > user override >
built-in.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

# Directory holding the built-in templates (this file's directory).
BUILTIN_DIR = Path(__file__).resolve().parent
_MANIFEST_FILE = BUILTIN_DIR / 'registry.yaml'
_CONFIG_FILES = ('agent.yaml', 'agent.yml')

# User-level override location: ~/.ms_agent/agents/<name>/
_USER_AGENTS_DIR = Path(os.path.expanduser('~/.ms_agent/agents'))
# Project-level override subdir (relative to a project root):
#   <project>/.ms-agent/agents/<name>/
_PROJECT_AGENTS_SUBDIR = os.path.join('.ms-agent', 'agents')


def _has_config(dir_path: Path) -> bool:
    return any((dir_path / name).is_file() for name in _CONFIG_FILES)


def is_template_name(name: str) -> bool:
    """A bare template name has no path separators (so it can never be confused
    with a local path or a ``org/repo`` ModelScope id)."""
    if not name or not isinstance(name, str):
        return False
    if os.sep in name or '/' in name:
        return False
    return True


def resolve_template_dir(name: str,
                         project_path: Optional[str] = None) -> Optional[str]:
    """Resolve a template *name* to a config directory.

    Priority: project override > user override > built-in. Returns ``None`` when
    the name is not a known template.
    """
    if not is_template_name(name):
        return None
    # 1) project-level override
    if project_path:
        cand = Path(project_path) / _PROJECT_AGENTS_SUBDIR / name
        if _has_config(cand):
            return str(cand)
    # 2) user-level override
    cand = _USER_AGENTS_DIR / name
    if _has_config(cand):
        return str(cand)
    # 3) built-in
    cand = BUILTIN_DIR / name
    if _has_config(cand):
        return str(cand)
    return None


def resolve_template_source(config_dir_or_id: str,
                            project_path: Optional[str] = None) -> str:
    """Passthrough resolver for the config-loading seams.

    - If ``config_dir_or_id`` is an existing path, return it unchanged (local
      wins).
    - Else if it is a known template name, return the resolved template dir.
    - Else return it unchanged (the caller's ModelScope fallback handles it).

    Importing the template package also triggers built-in harness callback
    registration (see ``ms_agent/agent/templates/__init__.py``), so that
    templates referencing ``callbacks: [stop_gate, ...]`` resolve without
    ``trust_remote_code``.
    """
    if not config_dir_or_id or not isinstance(config_dir_or_id, str):
        return config_dir_or_id
    if os.path.exists(config_dir_or_id):
        return config_dir_or_id
    resolved = resolve_template_dir(config_dir_or_id, project_path=project_path)
    return resolved if resolved is not None else config_dir_or_id


def load_manifest() -> Dict[str, dict]:
    """Load ``registry.yaml`` -> ``{name: {description, mode, when_to_use,
    model_tier}}``. Returns ``{}`` if the manifest is missing/unreadable."""
    if not _MANIFEST_FILE.is_file():
        return {}
    try:
        # Lazy import keeps the hot resolution path free of omegaconf.
        from omegaconf import OmegaConf
        data = OmegaConf.to_container(
            OmegaConf.load(str(_MANIFEST_FILE)), resolve=True)
    except Exception:
        return {}
    templates = (data or {}).get('templates', {}) or {}
    return {str(k): (v or {}) for k, v in templates.items()}


def list_templates(mode: Optional[str] = None) -> List[dict]:
    """List templates from the manifest. When ``mode`` is given, include only
    templates whose mode matches it or is ``all`` (e.g. ``mode='primary'``
    returns entry-point templates for a UI selector)."""
    out: List[dict] = []
    for name, meta in load_manifest().items():
        if mode is not None and meta.get('mode') not in (mode, 'all'):
            continue
        out.append({'name': name, **meta})
    return out


def get_when_to_use(name: str) -> str:
    """Delegation description for a template (used to synthesize the sub-agent
    tool description in ``expand_subagents``)."""
    meta = load_manifest().get(name) or {}
    return (meta.get('when_to_use') or meta.get('description')
            or f'Delegate a subtask to the {name} sub-agent.')
