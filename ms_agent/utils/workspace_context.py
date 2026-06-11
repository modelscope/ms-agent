"""Lightweight workspace context: root directory and deny globs for file traversal."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


_DEFAULT_DENY_GLOBS: tuple[str, ...] = ('**/.git/**',)
_MISSING = object()


def resolve_workspace_root(config: Any) -> Path:
    """Resolve the agent workspace root (``output_dir``).

    When ``output_dir`` is omitted or empty in config, defaults to the process
    current working directory (the user's workspace). Explicit values are
    expanded and resolved to an absolute path.
    """
    raw = getattr(config, 'output_dir', _MISSING)
    if raw is _MISSING or raw is None:
        return Path.cwd().resolve()
    text = str(raw).strip()
    if not text:
        return Path.cwd().resolve()
    return Path(text).expanduser().resolve()


@dataclass(frozen=True)
class WorkspaceContext:
    """Runtime context for tools — no security checks, only cwd and traversal filtering."""

    root: Path
    deny_globs: tuple[str, ...] = _DEFAULT_DENY_GLOBS

    @classmethod
    def from_config(cls, config: Any) -> WorkspaceContext:
        wp = getattr(getattr(config, 'tools', None), 'workspace_policy', None)
        raw_deny = list(getattr(wp, 'deny_globs', []) or []) if wp else []
        deny = tuple(raw_deny) if raw_deny else _DEFAULT_DENY_GLOBS

        return cls(root=resolve_workspace_root(config), deny_globs=deny)
