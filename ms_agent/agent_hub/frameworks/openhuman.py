# Copyright (c) ModelScope Contributors. All rights reserved.
"""OpenHuman workspace specification (single-agent install)."""
from __future__ import annotations

import re
from pathlib import Path

from .._workspace import (DEFAULT_AGENT_NAME, WorkspaceSpec, is_secret_key,
                          register_framework)


class OpenhumanWorkspace(WorkspaceSpec):
    """Workspace spec for the OpenHuman agent framework (root-per-agent).

    OpenHuman is a Rust/Tauri desktop app whose brain is a local Memory Tree
    (SQLite at ``memory_tree/chunks.db``) mirrored as an Obsidian-style
    ``wiki/`` Markdown vault.  Per its "move to a new PC" guide the portable,
    human-authored state is: the ``wiki/`` vault, the persona files
    ``SOUL.md`` / ``IDENTITY.md`` / ``HEARTBEAT.md`` and the ``config.toml``
    settings (models / providers / routing / autonomy).

    On-disk layout: the app does NOT keep those files directly under
    ``~/.openhuman`` -- they live in a per-device user workspace
    ``~/.openhuman/users/<user-id>/workspace/``, where ``<user-id>`` (e.g.
    ``local-u-mwj2l941-2317-local``) differs on every machine. The data root
    is therefore probed at runtime rather than hardcoded (BUG-033); a fixed
    ``~/.openhuman`` root collected zero files on real installs.

    Sub-agents are Profile personas: ``personalities/<Profile>/SOUL.md`` is a
    self-contained persona per Profile, so each Profile directory maps 1:1 to
    an agent (root-per-agent). The workspace-level ``SOUL.md`` is the global
    default persona and is collected as the ``default`` agent -- matching the
    app's own lookup order (Profile persona > ``soul_md_path`` override >
    inline persona > global default).

    Deliberately *not* collected: the SQLite stores (``memory_tree/chunks.db``,
    ``approval/approval.db``, ``mcp_clients/mcp_clients.db``) and the session
    history (``sessions/`` / ``session_raw/``) -- binary / run-time state that
    does not migrate across frameworks (the wiki is the readable mirror).
    """

    # Per-device user workspace: ``users/<user-id>/workspace``. The id segment
    # is machine-generated, so it is discovered by scanning rather than named.
    _USERS_DIRNAME = 'users'
    _WORKSPACE_DIRNAME = 'workspace'
    _PROFILES_DIRNAME = 'personalities'

    @property
    def product_name(self) -> str:
        return 'openhuman'

    @property
    def default_root(self) -> Path:
        """Resolve the per-device user workspace under ``~/.openhuman``.

        Returns ``<home>/.openhuman/users/<user-id>/workspace`` for the single
        installed user; when several user dirs exist the one with a
        ``workspace/`` subdir wins (deterministic: first in sorted order). On a
        fresh install with no ``users/`` tree yet, falls back to
        ``~/.openhuman`` so ``status`` still reports a sensible path instead of
        raising.
        """
        base = Path.home() / '.openhuman'
        return self._resolve_workspace(base)

    @classmethod
    def _resolve_workspace(cls, base: Path) -> Path:
        """Find the ``users/<id>/workspace`` dir under *base*.

        Also accepts *base* already BEING a user workspace (it directly holds
        ``personalities/`` or the persona files), so an explicit ``local_dir``
        may point at either the ``.openhuman`` root or the workspace itself.
        """
        users = base / cls._USERS_DIRNAME
        if users.is_dir():
            candidates = [d for d in sorted(users.iterdir()) if d.is_dir()]
            for d in candidates:
                ws = d / cls._WORKSPACE_DIRNAME
                if ws.is_dir():
                    return ws
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
        # fnmatch ``*`` spans ``/`` so ``wiki/*`` / ``skills/*`` recurse the
        # whole vault / skill tree.
        return [
            'SOUL.md',
            'IDENTITY.md',
            'HEARTBEAT.md',
            'config.toml',
            'wiki/*',
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
        # Allow dotted keys (``model.api_key = ...``) and test the last segment
        # so ``a.b.api_key`` is caught, not just a bare top-level ``api_key``.
        # Beyond simple ``key = <scalar>`` lines this also covers:
        # * inline tables  ``provider = { api_key = "X" }`` (incl. nested) --
        #   secret pairs inside the braces are cleared in place;
        # * arrays         ``tokens = ["X"]`` -> ``tokens = []``;
        # * multi-line strings (``secret = '''`` / ``\"\"\"``) -- the opener is
        #   blanked and the content lines up to the closing delimiter dropped.
        pattern = re.compile(
            r'^(?P<pre>\s*(?P<key>[A-Za-z0-9_.-]+)\s*=\s*)(?P<val>.*)$')
        inline_pair = re.compile(r'(?P<key>[A-Za-z0-9_.-]+)(?P<sep>\s*=\s*)'
                                 r'(?P<val>"[^"]*"|\'[^\']*\'|[^,{}\s][^,}]*)')
        out: list[str] = []
        lines = text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            m = pattern.match(line)
            if not m:
                out.append(line)
                i += 1
                continue
            key = m.group('key').split('.')[-1]
            val = m.group('val')
            vstrip = val.strip()
            if is_secret_key(key):
                # Multi-line string: blank the opener and drop content lines
                # up to (and including) the closing delimiter.
                delim = next((d for d in ('"""', "'''")
                              if vstrip.startswith(d) and vstrip.count(d) < 2),
                             None)
                if delim:
                    out.append(m.group('pre') + '""')
                    i += 1
                    while i < len(lines) and delim not in lines[i]:
                        i += 1
                    i += 1  # skip the closing-delimiter line
                    continue
                if vstrip.startswith('['):
                    out.append(m.group('pre') + '[]')
                    if ']' not in vstrip:  # multi-line array
                        i += 1
                        while i < len(lines) and ']' not in lines[i]:
                            i += 1
                    i += 1
                    continue
                out.append(m.group('pre') + '""')
                i += 1
                continue
            # Non-secret key: still scrub secret pairs inside inline tables
            # (``provider = { api_key = "X" }``, nested tables included).
            if '{' in vstrip:
                out.append(
                    m.group('pre') + inline_pair.sub(
                        lambda pm: f"{pm.group('key')}{pm.group('sep')}\"\""
                        if is_secret_key(pm.group('key').split('.')[-1]) else
                        pm.group(0), val))
                i += 1
                continue
            out.append(line)
            i += 1
        return '\n'.join(out)


register_framework('openhuman', OpenhumanWorkspace)
