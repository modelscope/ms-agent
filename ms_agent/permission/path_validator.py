"""Single-path validation: quote stripping, tilde expansion, shell-expansion
rejection, glob handling, directory-scope checks, and dangerous-path detection."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

GLOB_CHARS = set('*?[]{}')
_CONSECUTIVE_SLASHES = re.compile(r'[/\\]+')
_WINDOWS_DRIVE_ROOT = re.compile(r'^[A-Za-z]:/?$')
_WINDOWS_DRIVE_CHILD = re.compile(r'^[A-Za-z]:/[^/]+$')
_ROOT_CHILD = re.compile(r'^/[^/]+$')


@dataclass(frozen=True)
class PathValidationResult:
    allowed: bool
    resolved_path: str
    action: Literal['allow', 'deny', 'ask']
    reason: str
    category: str = ''


def _strip_quotes(path: str) -> str:
    if len(path) >= 2:
        if (path[0] == path[-1]) and path[0] in ('"', "'"):
            return path[1:-1]
    return path


def _expand_tilde(path: str, home_dir: str) -> tuple[str, str | None]:
    """Expand ``~`` and ``~/...``. Reject ``~user``, ``~+``, ``~-``."""
    if not path.startswith('~'):
        return path, None
    if path == '~':
        return home_dir, None
    if path.startswith('~/') or path.startswith('~\\'):
        return home_dir + path[1:], None
    return path, f'Unsupported tilde expansion: {path}'


def _has_shell_expansion(path: str) -> str | None:
    if '$' in path:
        return f'Path contains shell variable expansion: {path}'
    if '%' in path:
        return f'Path contains Windows variable expansion: {path}'
    if path.startswith('='):
        return f'Path starts with = (Zsh expansion): {path}'
    return None


def _has_glob(path: str) -> bool:
    return bool(GLOB_CHARS & set(path))


def get_glob_base_directory(pattern: str) -> str:
    """Extract the directory prefix before the first glob character."""
    first_glob = len(pattern)
    for i, c in enumerate(pattern):
        if c in GLOB_CHARS:
            first_glob = i
            break
    base = pattern[:first_glob]
    last_sep = base.rfind('/')
    if last_sep < 0:
        return '.'
    return base[:last_sep] or '/'


def _is_under_allowed(resolved: Path, allowed_dirs: Sequence[str]) -> bool:
    for d in allowed_dirs:
        try:
            resolved.relative_to(Path(d).resolve())
            return True
        except ValueError:
            continue
    return False


def validate_path(
    path: str,
    cwd: str,
    allowed_dirs: Sequence[str],
    op_type: Literal['read', 'write', 'create'],
    *,
    read_only_dirs: Sequence[str] = (),
    home_dir: str | None = None,
) -> PathValidationResult:
    """Validate a single filesystem path for a given operation type.

    Returns a ``PathValidationResult`` with ``allowed=True`` if the path passes
    all checks, or ``allowed=False`` with a reason explaining the rejection.
    """
    if home_dir is None:
        home_dir = os.path.expanduser('~')

    path = _strip_quotes(path)

    path, tilde_err = _expand_tilde(path, home_dir)
    if tilde_err:
        return PathValidationResult(
            allowed=False, resolved_path=path, action='deny', reason=tilde_err,
        )

    expansion_err = _has_shell_expansion(path)
    if expansion_err:
        return PathValidationResult(
            allowed=False, resolved_path=path, action='ask', reason=expansion_err,
            category='shell_expansion',
        )

    if _has_glob(path):
        if op_type in ('write', 'create'):
            return PathValidationResult(
                allowed=False, resolved_path=path, action='deny',
                reason=f'Glob patterns not allowed in {op_type} operations: {path}',
            )
        path = get_glob_base_directory(path)

    if os.path.isabs(path):
        resolved = Path(path).resolve()
    else:
        resolved = (Path(cwd) / path).resolve()

    resolved_str = str(resolved)

    if not _is_under_allowed(resolved, allowed_dirs):
        if op_type == 'read':
            if _is_under_allowed(resolved, read_only_dirs):
                return PathValidationResult(
                    allowed=True, resolved_path=resolved_str, action='allow',
                    reason='Path allowed via read-only directory',
                )
            return PathValidationResult(
                allowed=False, resolved_path=resolved_str, action='ask',
                reason=f'Read path outside allowed directories: {resolved_str}',
                category='read_outside_dirs',
            )
        return PathValidationResult(
            allowed=False, resolved_path=resolved_str, action='deny',
            reason=f'{op_type.capitalize()} path outside allowed directories: {resolved_str}',
        )

    return PathValidationResult(
        allowed=True, resolved_path=resolved_str, action='allow',
        reason='Path validation passed',
    )


def is_dangerous_removal_path(path: str) -> bool:
    """Check if a path is too dangerous for rm/rmdir, even within allowed dirs."""
    normalized = _CONSECUTIVE_SLASHES.sub('/', path)
    if normalized.endswith('/') and len(normalized) > 1:
        normalized = normalized.rstrip('/')

    if normalized == '*':
        return True
    if normalized.endswith('/*') or normalized.endswith('\\*'):
        return True
    if normalized == '/':
        return True

    home = os.path.expanduser('~').replace('\\', '/')
    if normalized == home:
        return True

    if _ROOT_CHILD.match(normalized):
        return True
    if _WINDOWS_DRIVE_ROOT.match(normalized):
        return True
    if _WINDOWS_DRIVE_CHILD.match(normalized):
        return True

    return False
