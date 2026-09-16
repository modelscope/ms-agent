# Copyright (c) ModelScope Contributors. All rights reserved.
"""OpenHuman workspace specification (single-agent install)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from ms_agent.utils.logger import get_logger
from .._workspace import (DEFAULT_AGENT_NAME, MAX_FILE_SIZE, WorkspaceSpec,
                          register_framework, scrub_toml_secrets)

logger = get_logger()


class OpenhumanWorkspace(WorkspaceSpec):
    """Workspace spec for the OpenHuman agent framework (root-per-agent).

    OpenHuman is a Rust/Tauri desktop app whose brain is a local Memory Tree
    (SQLite at ``memory_tree/chunks.db``).  The portable human-authored state
    is the persona files (``SOUL.md`` / ``IDENTITY.md`` / ``HEARTBEAT.md``),
    the curated ``MEMORY.md`` (+ the workspace-wide ``MEMORY_GOALS.md``),
    ``config.toml`` and the skill tree.  ``MEMORY.md`` is injected into the
    system prompt every session and is the only memory file the agent may
    write.

    Files live in a per-device workspace
    ``~/.openhuman/users/<user-id>/workspace/`` (the id differs on every
    machine, so the root is probed at runtime, BUG-033); ``config.toml``
    lives ONE LEVEL ABOVE it. Sub-agents are Profile personas
    (``personalities/<Profile>/``, root-per-agent). The app's lookup treats
    an EMPTY file as absent and falls back to the workspace copy -- mirrored
    by :meth:`_with_workspace_fallbacks`.

    Not collected: the SQLite stores, KV memory docs (machine-extracted chat
    derivatives), Memory Tree chunk mirrors, the derived wiki vault
    (regenerable summary output) and session history.
    """

    # Per-device user workspace: ``users/<user-id>/workspace``. The id segment
    # is machine-generated, so it is discovered by scanning rather than named.
    _DATA_DIRNAME = '.openhuman'
    _USERS_DIRNAME = 'users'
    _WORKSPACE_DIRNAME = 'workspace'
    _PROFILES_DIRNAME = 'personalities'
    _PROFILES_JSON_FILENAME = 'agent_profiles.json'

    # Liveness markers used to SCORE candidate user workspaces when several
    # exist (app reinstalls / user-id scheme migrations leave stale siblings
    # behind, and a sorted-first pick silently resolved to the stale one --
    # BUG-0828). ``agent_profiles.json`` is the profile registry the app only
    # writes where a user actually runs; ``personalities/`` holds the Profile
    # personas; ``SOUL.md`` is a weak signal (stale shells keep a copy too).
    _LIVENESS_SCORES: tuple[tuple[str, int], ...] = (
        (_PROFILES_JSON_FILENAME, 4),
        (_PROFILES_DIRNAME, 2),
        ('SOUL.md', 1),
    )

    # Files that fall back to the workspace-level copy when a Profile does
    # not carry its own -- the app's own lookup order, where an EMPTY file
    # counts as absent. MEMORY_GOALS.md is a workspace-wide singleton (every
    # Profile reads it from the root), so it always falls back. config.toml
    # is handled separately (it lives above the workspace); wiki/skills are
    # large trees whose per-profile duplication would bloat upload/sync.
    _WORKSPACE_FALLBACK_FILES = frozenset([
        'SOUL.md', 'IDENTITY.md', 'HEARTBEAT.md', 'MEMORY.md',
        'MEMORY_GOALS.md'
    ])

    @property
    def product_name(self) -> str:
        return 'openhuman'

    @property
    def default_root(self) -> Path:
        """Resolve the per-device user workspace under ``~/.openhuman``.

        Returns ``<home>/.openhuman/users/<user-id>/workspace`` for the
        installed users; when several user dirs exist the LIVE one wins by
        liveness score (see :meth:`_resolve_workspace`), with sorted order as
        the deterministic tie-break. On a fresh install with no ``users/``
        tree yet, falls back to ``~/.openhuman`` so ``status`` still reports
        a sensible path instead of raising.
        """
        base = Path.home() / '.openhuman'
        return self._resolve_workspace(base)

    @classmethod
    def _workspace_score(cls, ws: Path) -> int:
        """Liveness score of a candidate user workspace (higher = more likely
        the one actually in use). See :data:`_LIVENESS_SCORES`."""
        score = 0
        for name, weight in cls._LIVENESS_SCORES:
            if (ws / name).exists():
                score += weight
        return score

    @classmethod
    def _resolve_workspace(cls, base: Path) -> Path:
        """Find the ``users/<id>/workspace`` dir under *base*.

        Also accepts *base* already BEING a user workspace (it directly holds
        ``personalities/`` or the persona files), so an explicit ``local_dir``
        may point at either the ``.openhuman`` root or the workspace itself --
        or even one level ABOVE the data root (a backup dir that merely
        CONTAINS ``.openhuman/``), which is descended into (BUG-0828).

        When several ``users/<id>/`` dirs exist, the LIVE workspace wins by
        liveness score (``agent_profiles.json`` / ``personalities/`` /
        ``SOUL.md``); ties and all-empty scores fall back to sorted order, so
        a single-user or fresh install behaves exactly as before (BUG-0828:
        a stale alphabetically-first user dir used to shadow the active one).
        """
        users = base / cls._USERS_DIRNAME
        if not users.is_dir():
            data_root = base / cls._DATA_DIRNAME
            if (data_root / cls._USERS_DIRNAME).is_dir():
                users = data_root / cls._USERS_DIRNAME
        if users.is_dir():
            candidates = sorted(d for d in users.iterdir() if d.is_dir())
            workspaces = [
                d / cls._WORKSPACE_DIRNAME for d in candidates
                if (d / cls._WORKSPACE_DIRNAME).is_dir()
            ]
            if workspaces:
                # ``max`` keeps the FIRST maximum in iteration order, and the
                # list is sorted -- so ties deterministically fall back to the
                # old sorted-first behavior.
                return max(workspaces, key=cls._workspace_score)
            if candidates:
                return candidates[0] / cls._WORKSPACE_DIRNAME
        return base

    @property
    def root(self) -> Path:
        # ``local_dir`` may be given as either the ``.openhuman`` data root or
        # the resolved user workspace; normalize both to the workspace.
        if self._local_dir is not None:
            return self._resolve_workspace(self._local_dir)
        return self.default_root

    @property
    def workspace_root(self) -> Path:
        # root-per-agent: each Profile is a directory under ``personalities/``.
        # ``default`` is the workspace-level global persona, and all-mode lifts
        # to the profiles dir so each Profile becomes a path prefix.
        base = self.root
        if self._is_all():
            return base / self._PROFILES_DIRNAME
        if self.agent_name in ('', DEFAULT_AGENT_NAME):
            return base
        return base / self._PROFILES_DIRNAME / self.agent_name

    @property
    def patterns(self) -> list[str]:
        # Relative to :attr:`workspace_root` (``personalities/<Profile>/``
        # for a named agent), so one list covers both scopes. ``config.toml``
        # really lives one level above; the pattern is just the resources
        # key -- the read/write is special-cased in collect/apply.
        return [
            'SOUL.md',
            'IDENTITY.md',
            'HEARTBEAT.md',
            'MEMORY.md',
            'MEMORY_GOALS.md',
            'config.toml',
            'skills/*',
        ]

    def _effective_patterns(self) -> list[str]:
        if self._is_all():
            return [f'*/{p}' for p in self.patterns]
        return self.patterns

    @property
    def is_root_per_agent(self) -> bool:
        return True

    def split_all_path(self, rel_path: str) -> tuple[str | None, str]:
        # Profile directory name IS the agent name: ``<Profile>/<bare>``.
        if '/' in rel_path:
            head, rest = rel_path.split('/', 1)
            return (head, rest)
        return (None, rel_path)

    def join_all_path(self, agent_name: str, bare_path: str) -> str:
        return f'{agent_name}/{bare_path}'

    def list_agents(self) -> list[str]:
        """Profiles under ``personalities/`` plus the global ``default``."""
        profiles = self.root / self._PROFILES_DIRNAME
        agents = []
        if profiles.is_dir():
            agents = [d.name for d in sorted(profiles.iterdir()) if d.is_dir()]
        if DEFAULT_AGENT_NAME not in agents:
            agents = [DEFAULT_AGENT_NAME] + agents
        return agents

    # ------------------------------------------------------------------
    # Active-profile auto-selection
    # ------------------------------------------------------------------

    def resolve_default_agent_name(self) -> str:
        """Omitted ``--name`` selects the ACTIVE profile, not bare ``default``.

        The app keeps the currently selected persona in
        ``agent_profiles.json`` (``activeProfileId``); converting without an
        explicit name should migrate that persona, matching what the user
        sees in the app. Strictly best-effort: a missing / malformed marker
        or an id whose directory does not exist falls back to ``default``
        (the workspace-level persona) without raising.
        """
        active = self._active_profile_id()
        if active and active in self.list_agents():
            return active
        return DEFAULT_AGENT_NAME

    def _active_profile_id(self) -> str | None:
        """Read ``activeProfileId`` from ``agent_profiles.json`` (best effort).

        Returns ``None`` on any failure (file absent, unreadable, not JSON,
        unexpected shape) -- callers treat that as "no active profile".
        """
        path = self.root / self._PROFILES_JSON_FILENAME
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        active = data.get('activeProfileId')
        if not isinstance(active, str) or not active.strip():
            return None
        return active.strip()

    # ------------------------------------------------------------------
    # Workspace-level persona fallback for Profile agents
    # ------------------------------------------------------------------

    def collect(self) -> dict[str, str]:
        resources = self._with_workspace_fallbacks(super().collect(), text=True)
        self._add_parent_config(resources, text=True)
        return resources

    def collect_bytes(self) -> dict[str, bytes]:
        resources = self._with_workspace_fallbacks(
            super().collect_bytes(), text=False)
        self._add_parent_config(resources, text=False)
        return resources

    def _parent_config_path(self) -> Path | None:
        """``users/<id>/config.toml`` -- one level above the workspace. Only
        resolved for the real install layout (workspace dir literally named
        ``workspace/``) so ``local_dir`` never reaches outside the pointed-at
        folder; ``None`` in all-mode (the config is shared per user)."""
        if self._is_all() or self.root.name != self._WORKSPACE_DIRNAME:
            return None
        candidate = self.root.parent / 'config.toml'
        return candidate if candidate.is_file() else None

    def _add_parent_config(self, resources: dict, *, text: bool) -> None:
        """Collect the user-level ``config.toml`` (one level above the
        patterns' reach), keyed workspace-relative; symmetric with apply."""
        path = self._parent_config_path()
        if path is None or 'config.toml' in resources:
            return
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                logger.warning('Skip large file %s (exceeds limit %d)', path,
                               MAX_FILE_SIZE)
                return
            resources['config.toml'] = (
                path.read_text(encoding='utf-8') if text else
                path.read_bytes())
        except (OSError, UnicodeDecodeError) as e:
            logger.warning('Skip %s: %s', path, e)

    def apply(self, resources: dict) -> list[str]:
        """Write resources back; shared files return to where the app reads
        them: ``config.toml`` to the user dir (one level above) and
        ``MEMORY_GOALS.md`` to the workspace root (goals are workspace-wide,
        a per-Profile copy would never be read)."""
        resources = dict(resources)
        relocated: dict[str, Path] = {}
        if not self._is_all():
            if 'config.toml' in resources \
                    and self.root.name == self._WORKSPACE_DIRNAME:
                relocated['config.toml'] = self.root.parent / 'config.toml'
            if 'MEMORY_GOALS.md' in resources \
                    and self.workspace_root != self.root:
                relocated['MEMORY_GOALS.md'] = self.root / 'MEMORY_GOALS.md'
        if not relocated:
            return super().apply(resources)
        rest = {k: v for k, v in resources.items() if k not in relocated}
        written = super().apply(rest)
        for rel, target in relocated.items():
            raw = resources[rel]
            raw = raw if isinstance(raw, bytes) else raw.encode('utf-8')
            sanitized = self.sanitize_inbound_file(rel, raw)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sanitized)
            written.append(str(target))
        return written

    def _with_workspace_fallbacks(self, resources: dict, *,
                                  text: bool) -> dict:
        """Fill missing OR BLANK Profile files from the workspace copies --
        the app treats an empty file as absent and falls back, so a 0-byte
        Profile file must not shadow the real workspace content. A Profile
        copy with substance wins; all-mode is exempt (shared files would
        duplicate across every Profile repo)."""
        if self._is_all() or self.workspace_root == self.root:
            return resources
        workspace_spec = copy.copy(self)
        workspace_spec.agent_name = DEFAULT_AGENT_NAME
        for rel, f in workspace_spec._walk_matched():
            if rel not in self._WORKSPACE_FALLBACK_FILES:
                continue
            existing = resources.get(rel)
            if existing is not None and existing.strip():
                continue
            try:
                content = (
                    f.read_text(encoding='utf-8') if text else f.read_bytes())
            except (OSError, UnicodeDecodeError) as e:
                logger.warning('Skip workspace fallback %s: %s', f, e)
                continue
            if content.strip():
                resources[rel] = content
        return resources

    # ------------------------------------------------------------------
    # config.toml secret sanitization (inbound + outbound)
    # ------------------------------------------------------------------

    def sanitize_inbound_file(self, rel_path: str, content: bytes) -> bytes:
        """Blank machine-local secrets in ``config.toml``.

        Line-level rewrite (stdlib has no TOML writer): any ``key = <value>``
        assignment whose key name matches :func:`is_secret_key` has its value
        cleared to ``""``, preserving the rest of the file verbatim. Non-TOML
        content is left untouched.

        OpenHuman does no machine-local identity rebinding, so the base-class
        outbound hook (which delegates here) reuses this same cleaning on the
        upload path -- no separate outbound override is needed.
        """
        if rel_path != 'config.toml':
            return content
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            return content
        return self._scrub_toml_secrets(text).encode('utf-8')

    def _scrub_toml_secrets(self, text: str) -> str:
        """Wrapper over the shared :func:`scrub_toml_secrets`, which moved to
        ``_workspace`` so the content-driven outbound layer can clean ``.toml``
        at any collected path with the same rules."""
        return scrub_toml_secrets(text)


register_framework('openhuman', OpenhumanWorkspace)
