# Copyright (c) ModelScope Contributors. All rights reserved.
"""Hermes workspace specification (root-per-agent).

Hermes stores the *default* agent at the install root (``~/.hermes/``) and every
*named* agent under ``~/.hermes/profiles/<name>/``.  Each agent is a
self-contained directory with its own ``SOUL.md``, ``memories/``, ``skills/``
and a ``config.yaml`` (which also holds the ``mcp_servers`` MCP block) -- i.e. a
root-per-agent layout (1 agent == 1 directory), directly analogous to OpenClaw
(whose named agents live in ``workspace-<name>/``).

File list is aligned with the official Hermes docs
(https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files):
``SOUL.md`` is the *global* personality file loaded only from HERMES_HOME; the
project-scoped context files (``.hermes.md``/``AGENTS.md``/``CLAUDE.md``/
``.cursorrules``) live beside the user's code, not in HERMES_HOME, so they are
out of scope for agent-home migration.
"""
from __future__ import annotations

from pathlib import Path

from .._workspace import (DEFAULT_AGENT_NAME, WorkspaceSpec,
                          register_framework, scrub_yaml_secrets)
from ._bundled_skills import BundledSkillFilterMixin


class HermesWorkspace(BundledSkillFilterMixin, WorkspaceSpec):
    """Workspace spec for the Hermes agent framework (root-per-agent).

    * default agent: ``~/.hermes/``
    * named agents:  ``~/.hermes/profiles/<name>/``

    In ``all`` mode, ``workspace_root`` lifts to ``~/.hermes/`` and patterns
    match both the root (default agent) and ``profiles/<name>/`` (named agents).
    """

    @property
    def product_name(self) -> str:
        return 'hermes'

    @property
    def default_root(self) -> Path:
        return Path.home() / '.hermes'

    @property
    def workspace_root(self) -> Path:
        base = self.root
        if self._is_all() or self.agent_name in ('', DEFAULT_AGENT_NAME):
            return base
        return base / 'profiles' / self.agent_name

    @property
    def patterns(self) -> list[str]:
        # NOTE: fnmatch ``*`` spans ``/``, so ``skills/*`` matches every file
        # under ``skills/`` at any nesting depth (category dirs, scripts,
        # references, schemas -- observed up to 7 levels deep). Hermes ships
        # both a bundled ``skills/`` and an official ``optional-skills/`` tree
        # sharing the same structure, so both are captured recursively.
        #
        # ``config.yaml`` carries the ``mcp_servers`` MCP block (plus model /
        # terminal settings); it is collected here and stripped of secrets on
        # both the inbound and outbound path via ``sanitize_inbound_file`` /
        # ``sanitize_outbound_file``.
        #
        # ``hooks/*`` are Hermes lifecycle hook definitions/scripts (a genuine
        # HERMES_HOME feature, cf. ``hermes_cli/hooks.py``). They shape runtime
        # behavior, so they travel for *same-framework* fidelity. No other
        # framework has a ``hooks/`` slot and hooks are absent from
        # ``SEMANTIC_GROUPS``, so on a cross-framework convert they resolve to
        # their own path, match no target pattern, and are dropped by the
        # ``dst_spec`` filter -- never folded into the catch-all persona file.
        return [
            'SOUL.md',
            'memories/*.md',
            'skills/*',
            'optional-skills/*',
            'config.yaml',
            'hooks/*',
        ]

    def _effective_patterns(self) -> list[str]:
        # In all mode we must capture BOTH the default agent (bare files at the
        # root) and every named agent (under ``profiles/<name>/``).  The two
        # pattern groups are mutually exclusive: bare ``SOUL.md`` never matches
        # ``profiles/x/SOUL.md`` (literal prefix differs) and ``profiles/*/...``
        # never matches the root files.
        if self._is_all():
            return self.patterns + [f'profiles/*/{p}' for p in self.patterns]
        return self.patterns

    @property
    def is_root_per_agent(self) -> bool:
        return True

    def split_all_path(self, rel_path: str) -> tuple[str | None, str]:
        # Named agents live under ``profiles/<name>/``; anything else is the
        # default agent living at the root.
        if rel_path.startswith('profiles/'):
            rest = rel_path[len('profiles/'):]
            if '/' in rest:
                head, bare = rest.split('/', 1)
                return (head, bare)
            return (None, rel_path)
        return (DEFAULT_AGENT_NAME, rel_path)

    def join_all_path(self, agent_name: str, bare_path: str) -> str:
        if agent_name in ('', DEFAULT_AGENT_NAME):
            return bare_path
        return f'profiles/{agent_name}/{bare_path}'

    def list_agents(self) -> list[str]:
        base = self.root
        agents: list[str] = []
        if (base / 'SOUL.md').is_file():
            agents.append(DEFAULT_AGENT_NAME)
        profiles = base / 'profiles'
        if profiles.is_dir():
            for d in sorted(profiles.iterdir()):
                if d.is_dir() and not d.name.startswith('.'):
                    agents.append(d.name)
        return agents or [DEFAULT_AGENT_NAME]

    # ------------------------------------------------------------------
    # config.yaml secret sanitization (inbound + outbound)
    # ------------------------------------------------------------------

    def _scrub_yaml_secrets(self, text: str) -> str:
        """Blank secret values in ``config.yaml`` line-by-line.

        Thin wrapper over the shared :func:`scrub_yaml_secrets` (which every
        YAML-config framework reuses): secret-named keys, ``env`` / ``headers``
        bags, ``args`` command lines and URL credentials, at any depth.
        """
        return scrub_yaml_secrets(text)

    def _sanitize_config_file(self, rel_path: str, content: bytes) -> bytes:
        """Blank secrets in ``config.yaml`` (identical on up- and download).

        Hermes performs no machine-local identity rebinding, so the inbound and
        outbound sanitize are the same: strip secrets, keep everything else.
        Non-``config.yaml`` files (and undecodable bytes) pass through verbatim.
        """
        if self._is_all():
            _agent, bare = self.split_all_path(rel_path)
            if bare != 'config.yaml':
                return content
        else:
            if rel_path != 'config.yaml':
                return content
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            return content
        return self._scrub_yaml_secrets(text).encode('utf-8')

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Strip secrets from inbound ``config.yaml`` (root or profiles/<name>/).

        Hermes does no machine-local identity rebinding, so the base-class
        outbound hook (which delegates here) reuses this same cleaning on the
        upload path -- no separate outbound override is needed.
        """
        return self._sanitize_config_file(rel_path, content)


register_framework('hermes', HermesWorkspace)
