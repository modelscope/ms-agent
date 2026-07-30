# Copyright (c) ModelScope Contributors. All rights reserved.
"""OpenHuman workspace specification (single-agent install)."""
from __future__ import annotations

import re
from pathlib import Path

from .._workspace import WorkspaceSpec, is_secret_key, register_framework


class OpenhumanWorkspace(WorkspaceSpec):
    """Workspace spec for the OpenHuman agent framework (single-agent install).

    OpenHuman is a Rust/Tauri desktop app whose brain is a local Memory Tree
    (SQLite at ``memory_tree/chunks.db``) mirrored as an Obsidian-style
    ``wiki/`` Markdown vault under ``~/.openhuman``.  Per its "move to a new
    PC" guide the portable, human-authored state is: the ``wiki/`` vault, the
    persona files ``SOUL.md`` / ``IDENTITY.md`` / ``HEARTBEAT.md`` and the
    ``config.toml`` settings (models / providers / routing / autonomy).

    Deliberately *not* collected: the SQLite stores (``memory_tree/chunks.db``,
    ``approval/approval.db``, ``mcp_clients/mcp_clients.db``) and the session
    history (``sessions/`` / ``session_raw/``) -- binary / run-time state that
    does not migrate across frameworks (the wiki is the readable mirror).
    """

    @property
    def product_name(self) -> str:
        return 'openhuman'

    @property
    def default_root(self) -> Path:
        return Path.home() / '.openhuman'

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
        pattern = re.compile(
            r'^(?P<pre>\s*(?P<key>[A-Za-z0-9_.-]+)\s*=\s*).*$')
        out: list[str] = []
        for line in text.split('\n'):
            m = pattern.match(line)
            if m and is_secret_key(m.group('key').split('.')[-1]):
                out.append(m.group('pre') + '""')
            else:
                out.append(line)
        return '\n'.join(out)


register_framework('openhuman', OpenhumanWorkspace)
