# Copyright (c) ModelScope Contributors. All rights reserved.
"""Bridge the managed config files into the agent runtime.

`MCPConfigManager` / `SkillsConfigManager` persist MCP servers and skill sources
to ``~/.ms_agent/{mcp,skills}.json`` (global) and ``<work_dir>/.ms_agent/*.json``
(project) — the UI truth. But the agent runtime doesn't read those files: it
takes MCP via the ``mcp_config`` kwarg and skills via ``config.skills``. This
module performs the translation (read managed files → feed the runtime), which
is exactly what a WebUI backend must also do, so it doubles as the reference.

Semantics (respecting the runtime's existing same-name-replace merge):
  * MCP   — global + project merged (project wins by name), **disabled dropped**,
            UI meta fields stripped; an explicit ``--mcp-server-file`` wins last.
  * Skill — managed sources appended to ``config.skills.sources`` (catalog dedups
            by skill_id), managed ``disabled`` unioned into ``config.skills.disabled``.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from omegaconf import OmegaConf

# UI/meta fields on a managed MCP entry that must not reach the runtime server
# config (the runtime just connects whatever is in mcpServers).
_MCP_META = frozenset({
    'enabled', 'meta', 'source', '_scope', 'mcp', 'implementation',
    'trust_remote_code', '_removed',
})


def resolve_mcp_config(
    global_home: str,
    work_dir: Optional[str],
    explicit_file: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build a ``{'mcpServers': {...}}`` dict for the agent's ``mcp_config``
    kwarg from the managed mcp.json files (+ optional explicit file), or None.
    """
    servers: Dict[str, Any] = {}
    try:
        from ms_agent.config import MCPConfigManager
        mm = MCPConfigManager(global_root=global_home, project_root=work_dir)
        # 'merged' requires a project_root; fall back to 'global' without one.
        scope = 'merged' if work_dir else 'global'
        for name, entry in (mm.list(scope) or {}).items():
            entry = dict(entry)
            if entry.get('enabled', True) is False:
                continue  # UI-disabled → do not connect
            servers[name] = {
                k: v for k, v in entry.items() if k not in _MCP_META
            }
    except Exception:
        pass
    # Explicit --mcp-server-file wins last (same-name replace).
    if explicit_file and os.path.isfile(explicit_file):
        try:
            with open(explicit_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            src = data.get('mcpServers', data) if isinstance(data, dict) else {}
            if isinstance(src, dict):
                servers.update(src)
        except Exception:
            pass
    return {'mcpServers': servers} if servers else None


def merge_skills_into_config(config, global_home: str, work_dir: Optional[str]):
    """Append managed skill sources + disabled from skills.json into
    ``config.skills`` (in place, returns config). Catalog dedups by skill_id."""
    try:
        from ms_agent.config.skills_manager import SkillsConfigManager
        from ms_agent.skill.sources import parse_skill_source
        merged = SkillsConfigManager(global_dir=global_home).load_merged(
            work_dir)
    except Exception:
        return config
    src_strings = merged.get('sources') or []
    disabled = merged.get('disabled') or []
    if not src_strings and not disabled:
        return config

    new_sources = []
    for s in src_strings:
        try:
            src = parse_skill_source(str(s))
            entry = {'type': src.type.value}
            for k in ('path', 'repo_id', 'url', 'revision', 'subdir'):
                v = getattr(src, k, None)
                if v:
                    entry[k] = v
            new_sources.append(entry)
        except Exception:
            continue

    skills = getattr(config, 'skills', None)
    existing_sources = []
    existing_disabled = []
    if skills is not None:
        raw = getattr(skills, 'sources', None)
        if raw:
            existing_sources = OmegaConf.to_container(raw, resolve=True) or []
        existing_disabled = list(getattr(skills, 'disabled', []) or [])

    combined_sources = list(existing_sources) + new_sources
    combined_disabled = list(
        dict.fromkeys(existing_disabled + list(disabled)))
    if combined_sources:
        OmegaConf.update(config, 'skills.sources', combined_sources,
                         merge=False)
    if combined_disabled:
        OmegaConf.update(config, 'skills.disabled', combined_disabled,
                         merge=False)
    return config
