# Copyright (c) ModelScope Contributors. All rights reserved.
"""Canonical on-disk layout (Claude Code / Codex aligned).

Single source of truth for where things live, so the runtime agent, the M1
project layer, and a future WebUI/Server all agree:

- **Working / project directory** == ``output_dir`` (one concept). Work products
  may be written anywhere under it, like any coding agent.
- **Framework internals** live under ``<work_dir>/.ms_agent/`` (memory, snapshots,
  project-level settings), collapsed into one namespace.
- **Session logs live globally**, decoupled from the work dir:
  ``~/.ms_agent/projects/<key>/<session>.jsonl`` where ``<key>`` is the escaped
  absolute path of the work dir (CC-style, zero-config per directory).

Legacy locations (``<work_dir>/sessions``, ``<work_dir>/.ms-agent``,
``<work_dir>/.ms_agent_snapshots``) are still *read* for back-compat.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

INTERNAL_DIR_NAME = '.ms_agent'  # project-local framework dir
LEGACY_INTERNAL_DIR_NAME = '.ms-agent'  # older hyphenated name (read-compat)


def global_home() -> Path:
    """The global ms-agent home. Read dynamically so ``MS_AGENT_HOME`` can be
    redirected (e.g. per-test) without re-importing."""
    return Path(os.environ.get('MS_AGENT_HOME', '~/.ms_agent')).expanduser()


# Back-compat module attribute; prefer global_home().
GLOBAL_HOME = global_home()


def _abs(work_dir: str | Path) -> Path:
    return Path(work_dir).expanduser().resolve()


def project_key(work_dir: str | Path) -> str:
    """CC-style stable key from the work dir's absolute path.

    ``/Users/x/proj`` -> ``-Users-x-proj``. Readable and directory-unique.
    """
    abs_path = str(_abs(work_dir))
    key = re.sub(r'[^A-Za-z0-9._-]+', '-', abs_path)
    return key.strip('-') or 'root'


def global_projects_root() -> Path:
    return global_home() / 'projects'


def global_project_dir(work_dir: str | Path) -> Path:
    """``~/.ms_agent/projects/<key>/`` — where sessions (and later project
    metadata) for this work dir live."""
    return global_projects_root() / project_key(work_dir)


def global_sessions_dir(work_dir: str | Path) -> Path:
    """Session logs live flat directly under the global project dir."""
    return global_project_dir(work_dir)


def local_internal_dir(work_dir: str | Path) -> Path:
    """``<work_dir>/.ms_agent/`` — framework internals for this project."""
    return _abs(work_dir) / INTERNAL_DIR_NAME


def legacy_local_internal_dir(work_dir: str | Path) -> Path:
    return _abs(work_dir) / LEGACY_INTERNAL_DIR_NAME


def snapshots_dir(work_dir: str | Path) -> Path:
    """``<work_dir>/.ms_agent/snapshots`` (was ``<work_dir>/.ms_agent_snapshots``)."""
    return local_internal_dir(work_dir) / 'snapshots'


def memory_dir(work_dir: str | Path) -> Path:
    """``<work_dir>/.ms_agent/memory`` (was ``<work_dir>/.memory`` / ``.default_memory``)."""
    return local_internal_dir(work_dir) / 'memory'


# ── generic + specific work-local internal subdirs ──────────────────────────
# Everything the framework writes for its own bookkeeping goes under one of
# these, so a work dir only ever contains the user's artifacts plus a single
# ``.ms_agent/`` namespace (no scattered ms_agent.log / .memory / .index / …).


def internal_subdir(work_dir: str | Path, *parts: str) -> Path:
    """``<work_dir>/.ms_agent/<parts...>``."""
    return local_internal_dir(work_dir).joinpath(*parts)


def artifacts_dir(work_dir: str | Path) -> Path:
    """Large tool-output spill (was ``<work_dir>/.ms_agent_artifacts``)."""
    return internal_subdir(work_dir, 'artifacts')


def index_dir(work_dir: str | Path) -> Path:
    """Search / filesystem / code indexes (was ``<work_dir>/.index``)."""
    return internal_subdir(work_dir, 'index')


def locks_dir(work_dir: str | Path) -> Path:
    """Lock files (was ``<work_dir>/.locks``)."""
    return internal_subdir(work_dir, 'locks')


def tmp_dir(work_dir: str | Path) -> Path:
    """Ephemeral working files (was ``<work_dir>/.temp``)."""
    return internal_subdir(work_dir, 'tmp')


def subagents_dir(work_dir: str | Path) -> Path:
    """Sub-agent stream logs (was ``<work_dir>/subagents``)."""
    return internal_subdir(work_dir, 'subagents')


def web_search_dir(work_dir: str | Path) -> Path:
    """Web-search payload spill (was ``<work_dir>/web_search_artifacts``)."""
    return internal_subdir(work_dir, 'web_search')


def search_index_dir(work_dir: str | Path, name: str = 'search') -> Path:
    """RAG / sirchmunk indexes (was ``./.sirchmunk`` / ``./llama_index``)."""
    return internal_subdir(work_dir, 'search_index', name)


def stats_file(work_dir: str | Path,
               name: str = 'workflow_stats.json') -> Path:
    """Token/usage stats (was ``<work_dir>/workflow_stats.json``)."""
    return internal_subdir(work_dir, name)


def global_logs_dir() -> Path:
    """``~/.ms_agent/logs`` — opt-in file logging target (never CWD)."""
    return global_home() / 'logs'


# ── project-local config dir (writes prefer new, reads fall back to legacy) ──


def project_internal_dir(project_path: str | Path) -> Path:
    """New project-local framework dir for **writes** (``<proj>/.ms_agent``)."""
    return _abs(project_path) / INTERNAL_DIR_NAME


def project_internal_file(project_path: str | Path, filename: str) -> Path:
    """Resolve ``<proj>/.ms_agent/<file>`` for reads, falling back to the legacy
    ``<proj>/.ms-agent/<file>`` when only the legacy exists. Returns the new-dir
    path when neither exists so callers treat "missing" uniformly. Writers
    should use ``project_internal_dir()`` (always the new dir)."""
    new = _abs(project_path) / INTERNAL_DIR_NAME / filename
    if new.exists():
        return new
    legacy = _abs(project_path) / LEGACY_INTERNAL_DIR_NAME / filename
    if legacy.exists():
        return legacy
    return new
