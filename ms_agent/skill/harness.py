# Copyright (c) ModelScope Contributors. All rights reserved.
"""Live path substitution for bundled harness skills.

No harness skill is bundled right now. Ids in ``HARNESS_SKILL_IDS`` get
``{home}`` / ``{work}`` / … filled at ``skill_view`` and slash-expand time.
Every other skill is left unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

HARNESS_SKILL_IDS: frozenset[str] = frozenset()


def harness_placeholders(config: Any = None) -> Dict[str, str]:
    """Resolve the machine's current home / work / memory / MCP paths."""
    from ms_agent.project.paths import global_home, memory_dir
    from ms_agent.utils.workspace_context import resolve_workspace_root

    try:
        home = str(global_home())
    except Exception:  # noqa: BLE001 - never break skill_view
        home = str(Path.home() / '.ms_agent')
    try:
        work = str(resolve_workspace_root(config))
    except Exception:  # noqa: BLE001
        work = str(Path.cwd().resolve())
    return {
        'home': home,
        'work': work,
        'memory_md': str(memory_dir(work) / 'MEMORY.md'),
        'project_mcp': str(Path(work) / '.ms_agent' / 'mcp.json'),
        'global_mcp': str(Path(home) / 'mcp.json'),
    }


def fill_harness_placeholders(
        text: str,
        config: Any = None,
        skill_id: Optional[str] = None) -> str:
    """Replace ``{home}`` / ``{work}`` / … in a harness skill body.

    Token replace (not ``str.format``) so JSON examples with other braces
    stay intact. Unknown skill ids are left unchanged.
    """
    if skill_id is not None and skill_id not in HARNESS_SKILL_IDS:
        return text
    mapping = harness_placeholders(config)
    for key, value in mapping.items():
        text = text.replace('{' + key + '}', value)
    return text
