# Copyright (c) ModelScope Contributors. All rights reserved.
"""Nanobot workspace specification (single-agent install)."""
from __future__ import annotations

from pathlib import Path

from .._workspace import WorkspaceSpec, register_framework


class NanobotWorkspace(WorkspaceSpec):
    """Workspace spec for the Nanobot agent framework (single-agent install).

    Nanobot keeps a single shared workspace at ``~/.nanobot/workspace``.  Its
    ``onboard`` command seeds ``AGENTS.md``, ``SOUL.md``, ``USER.md`` and the
    ``HEARTBEAT.md`` task file; reusable prompts live under ``prompts/`` and
    long-term memory under ``memory/`` -- ``memory/MEMORY.md`` plus the
    append-only event log ``memory/history.jsonl`` (the legacy ``HISTORY.md``
    was replaced by the JSONL log).  Sub-agents run as background sessions
    (no on-disk per-agent files), so this is single-agent.

    Note that the install root and the data root differ by one level: the
    files sit in ``workspace/``, not directly under ``~/.nanobot``.  Declaring
    ``_ROOT_SUBDIRS`` lets a ``--local_dir`` pointing at the install root be
    accepted too, which otherwise failed with "no nanobot files found".
    """

    # ``.nanobot`` (install root) -> ``.nanobot/workspace`` (data root).
    _ROOT_SUBDIRS = ('workspace', )

    @property
    def product_name(self) -> str:
        return 'nanobot'

    @property
    def default_root(self) -> Path:
        return Path.home() / '.nanobot' / 'workspace'

    @property
    def patterns(self) -> list[str]:
        # fnmatch ``*`` spans ``/`` so ``skills/*`` recurses the whole skill
        # tree (SKILL.md + scripts/references/assets at any depth).
        return [
            'AGENTS.md',
            'SOUL.md',
            'USER.md',
            'HEARTBEAT.md',
            'prompts/*.md',
            'memory/MEMORY.md',
            'memory/history.jsonl',
            'skills/*',
        ]


register_framework('nanobot', NanobotWorkspace)
