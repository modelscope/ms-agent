# Copyright (c) ModelScope Contributors. All rights reserved.
"""Qoder workspace specification (file-per-agent + shared)."""
from __future__ import annotations

from pathlib import Path

from .._workspace import DEFAULT_AGENT_NAME, WorkspaceSpec, register_framework


class QoderWorkspace(WorkspaceSpec):
    """Workspace spec for the Qoder agent framework.

    Qoder keeps user-level config at ``~/.qoder`` (project-level config lives in
    a project's ``.qoder/`` directory; point ``--local_dir`` at it to upload
    that instead).  A sub-agent is one Markdown file ``agents/<name>.md``; skills,
    commands, rules and ``AGENTS.md`` are shared across sub-agents.
    """

    @property
    def product_name(self) -> str:
        return 'qoder'

    @property
    def supports_individual_watch(self) -> bool:
        return False

    @property
    def default_root(self) -> Path:
        return Path.home() / '.qoder'

    @property
    def patterns(self) -> list[str]:
        return [
            'AGENTS.md',
            'agents/{name}.md',
            'commands/*.md',
            'rules/*.md',
            'skills/*/SKILL.md',
            'skills/*/scripts/*',
            'skills/*/references/*',
        ]

    def list_agents(self) -> list[str]:
        return self._list_agents_from_dir(self.workspace_root / 'agents')


register_framework('qoder', QoderWorkspace)
