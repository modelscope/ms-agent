# Copyright (c) ModelScope Contributors. All rights reserved.
"""Workspace path policy: allow-roots (default output_dir) and optional deny globs."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Iterable, Sequence


class WorkspacePolicyError(ValueError):
    """Raised when a path or command violates workspace policy."""


class WorkspacePolicyKernel:
    """Resolve user paths under allowed workspace roots; optional shell read-only rules."""

    def __init__(
        self,
        output_dir: Path | str,
        *,
        extra_allow_roots: Sequence[str | Path] | None = None,
        deny_globs: Sequence[str] | None = None,
        shell_default_mode: str = 'workspace_write',
        shell_network_enabled: bool = False,
        max_command_chars: int = 8192,
    ) -> None:
        self._output = Path(output_dir).expanduser().resolve()
        self._roots: list[Path] = [self._output]
        if extra_allow_roots:
            for r in extra_allow_roots:
                p = Path(r).expanduser().resolve()
                if p not in self._roots:
                    self._roots.append(p)
        if deny_globs is None or len(tuple(deny_globs)) == 0:
            self._deny_globs: tuple[str, ...] = ('**/.git/**',)
        else:
            self._deny_globs = tuple(deny_globs)
        self.shell_default_mode = shell_default_mode
        self.shell_network_enabled = shell_network_enabled
        self.max_command_chars = max_command_chars

    @property
    def workspace_root(self) -> Path:
        return self._output

    @property
    def allow_roots(self) -> tuple[Path, ...]:
        return tuple(self._roots)

    @property
    def deny_globs(self) -> tuple[str, ...]:
        return self._deny_globs

    def resolve_under_roots(self, user_path: str | Path) -> Path:
        """Resolve *user_path* to an absolute path that must lie under one allow root."""
        raw = Path(user_path).expanduser()
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = (self._output / raw).resolve()
        for root in self._roots:
            try:
                resolved.relative_to(root)
                break
            except ValueError:
                continue
        else:
            raise WorkspacePolicyError(
                f'Path is outside allowed workspace roots: {resolved}')
        if self._is_denied(resolved):
            raise WorkspacePolicyError(
                f'Path matches a deny_globs pattern: {resolved}')
        return resolved

    def _is_denied(self, path: Path) -> bool:
        if not self._deny_globs:
            return False
        rel = None
        try:
            rel = path.relative_to(self._output)
        except ValueError:
            rel = path
        rel_s = rel.as_posix()
        for pat in self._deny_globs:
            if fnmatch.fnmatch(rel_s, pat) or fnmatch.fnmatch(path.name, pat):
                return True
            if fnmatch.fnmatch(str(path), pat):
                return True
        return False

    def path_is_allowed(self, path: Path) -> bool:
        path = path.expanduser().resolve()
        for root in self._roots:
            try:
                path.relative_to(root)
                break
            except ValueError:
                continue
        else:
            return False
        return not self._is_denied(path)

    def assert_shell_command_allowed(self, command: str) -> None:
        """Length and mode-based checks before executing shell."""
        if not command or not command.strip():
            raise WorkspacePolicyError('Empty shell command')
        if len(command) > self.max_command_chars:
            raise WorkspacePolicyError(
                f'Shell command exceeds max length ({self.max_command_chars})')

        mode = self.shell_default_mode
        if mode == 'read_only':
            if _shell_looks_mutating_or_network(command,
                                                allow_network=False):
                raise WorkspacePolicyError(
                    'Shell is in read_only mode: mutating or network commands are not allowed'
                )
        elif mode == 'workspace_write':
            if not self.shell_network_enabled and _shell_looks_network(command):
                raise WorkspacePolicyError(
                    'Network commands are disabled for shell (enable tools.code_executor.shell.network_enabled)'
                )
        # future: explicit 'network' mode could allow curl etc.


def _shell_looks_network(command: str) -> bool:
    lowered = command.lower()
    tokens = (
        'curl ',
        'wget ',
        'ssh ',
        'scp ',
        'rsync ',
        'ftp ',
        'nc ',
        'netcat ',
        'pip install',
        'pip3 install',
        'npm install',
        'yarn add',
        'pnpm add',
    )
    return any(t in lowered for t in tokens)


def _shell_looks_mutating_or_network(command: str, *,
                                     allow_network: bool) -> bool:
    if not allow_network and _shell_looks_network(command):
        return True
    # redirection that creates/overwrites files
    if re.search(r'[>]{1,2}\s*[^\s]', command):
        return True
    if re.search(r'\b(rm|rmdir|mv|cp|chmod|chown|chgrp|mkdir|touch|tee)\b',
                 command):
        return True
    return False


def iter_files_under(
    root: Path,
    *,
    deny_globs: Iterable[str] = (),
    max_files: int = 100_000,
) -> Iterable[Path]:
    """Yield files under *root* (depth-first), skipping directories matching deny globs."""
    deny = tuple(deny_globs)
    count = 0
    root = root.resolve()

    def dir_skipped(dirpath: Path) -> bool:
        try:
            rel = dirpath.relative_to(root).as_posix()
        except ValueError:
            return True
        for pat in deny:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel + '/', pat):
                return True
            parts = rel.split('/')
            for i in range(len(parts)):
                sub = '/'.join(parts[:i + 1])
                if fnmatch.fnmatch(sub, pat.rstrip('/')) or fnmatch.fnmatch(
                        sub + '/', pat):
                    return True
        return False

    for dirpath, dirnames, filenames in os.walk(
            root, topdown=True, followlinks=False):
        dp = Path(dirpath)
        if dir_skipped(dp):
            dirnames[:] = []
            continue
        # prune skipped subdirs
        keep: list[str] = []
        for d in dirnames:
            child = dp / d
            if dir_skipped(child):
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            count += 1
            if count > max_files:
                return
            yield dp / name
