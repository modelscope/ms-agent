# Copyright (c) ModelScope Contributors. All rights reserved.
"""OpenClaw workspace specification (root-per-agent)."""
from __future__ import annotations

from pathlib import Path

from .._workspace import DEFAULT_AGENT_NAME, WorkspaceSpec, register_framework


class OpenclawWorkspace(WorkspaceSpec):
    """Workspace spec for the OpenClaw agent framework.

    The default agent lives in ``~/.openclaw/workspace``; named agents live in
    ``~/.openclaw/workspace-<name>``.

    In ``all`` mode, ``workspace_root`` lifts to ``~/.openclaw/`` and patterns
    are prefixed with ``workspace*/`` to match both ``workspace/`` (default) and
    ``workspace-<name>/`` directories.
    """

    @property
    def product_name(self) -> str:
        return 'openclaw'

    @property
    def default_root(self) -> Path:
        return Path.home() / '.openclaw'

    @property
    def workspace_root(self) -> Path:
        base = self.root
        if self._is_all():
            return base
        if self.agent_name in ('', DEFAULT_AGENT_NAME):
            return base / 'workspace'
        return base / f'workspace-{self.agent_name}'

    @property
    def patterns(self) -> list[str]:
        # NOTE: fnmatch ``*`` spans ``/``, so ``skills/*`` matches every file
        # under a skill dir at any depth (SKILL.md, _meta.json, scripts/,
        # references/, schemas/, ...). Aligned with the official OpenClaw
        # workspace file map (docs.openclaw.ai/concepts/agent-workspace):
        # BOOT.md (startup checklist) is a standard workspace file distinct
        # from BOOTSTRAP.md (one-time first-run ritual). canvas/ (UI .html) is
        # intentionally excluded -- it is not portable persona/memory/skill.
        return [
            'AGENTS.md',
            'SOUL.md',
            'USER.md',
            'TOOLS.md',
            'HEARTBEAT.md',
            'IDENTITY.md',
            'BOOT.md',
            'BOOTSTRAP.md',
            'MEMORY.md',
            'memory/*.md',
            'memory/*.json',
            'skills/*',
        ]

    def _effective_patterns(self) -> list[str]:
        if self._is_all():
            return [f'workspace*/{p}' for p in self.patterns]
        return self.patterns

    @property
    def is_root_per_agent(self) -> bool:
        return True

    def split_all_path(self, rel_path: str) -> tuple[str | None, str]:
        # agent lives in ``workspace/`` (default) or ``workspace-<name>/``.
        if '/' not in rel_path:
            return (None, rel_path)
        head, rest = rel_path.split('/', 1)
        if head == 'workspace':
            return (DEFAULT_AGENT_NAME, rest)
        if head.startswith('workspace-'):
            return (head[len('workspace-'):], rest)
        return (None, rel_path)

    def join_all_path(self, agent_name: str, bare_path: str) -> str:
        if agent_name in ('', DEFAULT_AGENT_NAME):
            return f'workspace/{bare_path}'
        return f'workspace-{agent_name}/{bare_path}'

    def list_agents(self) -> list[str]:
        base = self.root
        agents: list[str] = []
        if (base / 'workspace').is_dir():
            agents.append(DEFAULT_AGENT_NAME)
        if base.is_dir():
            for d in sorted(base.glob('workspace-*')):
                if d.is_dir():
                    agents.append(d.name[len('workspace-'):])
        return agents or [DEFAULT_AGENT_NAME]


register_framework('openclaw', OpenclawWorkspace)
