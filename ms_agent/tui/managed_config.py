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
import re

from omegaconf import OmegaConf
from typing import Any, Dict, Optional

# UI/meta fields on a managed MCP entry that must not reach the runtime server
# config (the runtime just connects whatever is in mcpServers).
_MCP_META = frozenset({
    'enabled',
    'meta',
    'source',
    '_scope',
    'mcp',
    'implementation',
    'trust_remote_code',
    '_removed',
})

#: ``${NAME}`` placeholders in managed MCP entries (headers, args, url, env
#: values). Deliberately braces-only — a bare ``$VAR`` in an arg stays what
#: the user typed.
_ENV_PLACEHOLDER_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def expand_env_placeholders(value: Any) -> Any:
    """Recursively expand ``${VAR}`` from the process environment.

    Runtime-only: the managed files and the management UI keep the
    placeholders (secrets never land on disk or on screen). An unresolved
    name stays verbatim, so a missing variable surfaces in the connection
    error instead of silently becoming an empty string.
    """
    if isinstance(value, str):
        return _ENV_PLACEHOLDER_RE.sub(
            lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: expand_env_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_placeholders(v) for v in value]
    return value


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
                k: v
                for k, v in entry.items() if k not in _MCP_META
            }
    except Exception:
        pass
    # Explicit --mcp-server-file wins last (same-name replace).
    if explicit_file and os.path.isfile(explicit_file):
        try:
            with open(explicit_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            src = data.get('mcpServers', data) if isinstance(data,
                                                             dict) else {}
            if isinstance(src, dict):
                servers.update(src)
        except Exception:
            pass
    if not servers:
        return None
    # ${VAR} placeholders resolve here — at the runtime boundary — so the
    # connection gets real credentials while every management surface keeps
    # the placeholder form.
    return {'mcpServers': expand_env_placeholders(servers)}


def merge_skills_into_config(config, global_home: str, work_dir: Optional[str]):
    """Merge managed skill sources + disabled from skills.json into
    ``config.skills`` (in place, returns config). Catalog dedups by skill_id.

    **Replayable**: managed source entries are tagged ``origin: 'managed'``
    and replaced wholesale on every call, and the config's own (yaml-layer)
    disabled list is stashed under ``skills._yaml_disabled`` on first merge so
    the effective ``disabled`` can be recomputed instead of unioned into
    staleness. Callers may therefore re-run this on a live agent's config to
    pick up skills.json changes mid-session (see SkillRuntime.sync_with_config).
    """
    try:
        from ms_agent.config.skills_manager import SkillsConfigManager
        merged = SkillsConfigManager(global_dir=global_home).load_merged(
            work_dir)
    except Exception:
        return config
    src_strings = merged.get('sources') or []
    disabled = merged.get('disabled') or []

    new_sources = _skill_sources_to_entries(src_strings)

    skills = getattr(config, 'skills', None)
    existing_sources = []
    stashed = None
    if skills is not None:
        raw = getattr(skills, 'sources', None)
        if raw:
            existing_sources = OmegaConf.to_container(raw, resolve=True) or []
        stashed = getattr(skills, '_yaml_disabled', None)
    if stashed is not None:
        yaml_disabled = list(stashed)
    else:
        # First merge: whatever disabled the config carries is the yaml layer.
        yaml_disabled = list(getattr(skills, 'disabled', []) or []) \
            if skills is not None else []

    base_sources = [
        e for e in existing_sources
        if not (isinstance(e, dict) and e.get('origin') == 'managed')
    ]

    # Untouched only when nothing is managed NOW and nothing managed was
    # merged BEFORE (no stash, no managed-tagged entries) — a replay with an
    # emptied managed layer must still strip the previous contribution.
    previously_merged = stashed is not None \
        or len(base_sources) != len(existing_sources)
    if not src_strings and not disabled and not previously_merged \
            and not base_sources and not yaml_disabled:
        return config

    combined_sources = base_sources + new_sources
    combined_disabled = list(dict.fromkeys(yaml_disabled + list(disabled)))
    OmegaConf.update(config, 'skills._yaml_disabled', yaml_disabled,
                     merge=False)
    if combined_sources or existing_sources:
        OmegaConf.update(config, 'skills.sources', combined_sources,
                         merge=False)
    if combined_disabled or getattr(skills, 'disabled', None):
        OmegaConf.update(config, 'skills.disabled', combined_disabled,
                         merge=False)
    return config


def _skill_sources_to_entries(src_strings) -> list:
    """Managed source strings -> typed entries for ``config.skills.sources``,
    each tagged ``origin: 'managed'`` so a re-merge can replace them."""
    from ms_agent.skill.sources import parse_skill_source

    entries = []
    for s in src_strings:
        try:
            src = parse_skill_source(str(s))
            entry = {'type': src.type.value, 'origin': 'managed'}
            for k in ('path', 'repo_id', 'url', 'revision', 'subdir'):
                v = getattr(src, k, None)
                if v:
                    entry[k] = v
            entries.append(entry)
        except Exception:
            continue
    return entries
