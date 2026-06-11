"""Configuration parsing for the permission module.

Reads the ``permission`` section from agent YAML and produces frozen
dataclasses consumed by SafetyGuard and PermissionEnforcer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

# Default safety rules baked into SafetyConfig when none are configured.
_DEFAULT_SAFETY_PATTERNS: tuple[str, ...] = (
    'code_executor---shell_executor:rm -rf /*',
    'code_executor---shell_executor:mkfs *',
    'code_executor---shell_executor:dd if=*',
)

_DEFAULT_SENSITIVE_PATHS: tuple[str, ...] = (
    '/etc/*',
    '/sys/*',
    '/boot/*',
    '/dev/*',
    '/proc/*',
    '~/.ssh/*',
    '~/.gnupg/*',
    '~/.bashrc',
    '~/.zshrc',
    '~/.profile',
    '.git/config',
    '.git/hooks/*',
    '**/.git/**',
)

_DEFAULT_DANGEROUS_REMOVAL: tuple[str, ...] = (
    '*',
    '/*',
    '/',
    '~',
)


@dataclass(frozen=True)
class SafetyConfig:
    """Inner-layer safety configuration (non-bypassable)."""
    patterns: tuple[str, ...] = _DEFAULT_SAFETY_PATTERNS
    sensitive_paths: tuple[str, ...] = _DEFAULT_SENSITIVE_PATHS
    dangerous_removal_paths: tuple[str, ...] = _DEFAULT_DANGEROUS_REMOVAL
    read_policy: Literal['loose', 'strict'] = 'loose'
    max_command_chars: int = 8192
    allowed_directories: tuple[str, ...] = ()
    read_only_directories: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict[str, Any], project_root: str | None = None) -> SafetyConfig:
        patterns = tuple(d.get('patterns', _DEFAULT_SAFETY_PATTERNS))
        sensitive = tuple(d.get('sensitive_paths', _DEFAULT_SENSITIVE_PATHS))
        dangerous = tuple(d.get('dangerous_removal_paths', _DEFAULT_DANGEROUS_REMOVAL))

        path_validation = d.get('path_validation', {})
        read_policy = path_validation.get('read_policy', 'loose')
        max_chars = path_validation.get('max_command_chars', 8192)

        def _expand_dirs(raw: list[str]) -> tuple[str, ...]:
            out: list[str] = []
            for entry in raw:
                if entry == '${PROJECT_ROOT}' and project_root:
                    out.append(project_root)
                else:
                    out.append(os.path.expandvars(entry))
            return tuple(out)

        allowed = _expand_dirs(list(d.get('allowed_directories', [])))
        read_only = _expand_dirs(list(d.get('read_only_directories', [])))

        return cls(
            patterns=patterns,
            sensitive_paths=sensitive,
            dangerous_removal_paths=dangerous,
            read_policy=read_policy,
            max_command_chars=max_chars,
            allowed_directories=allowed,
            read_only_directories=read_only,
        )


_DEFAULT_BLACKLIST: tuple[str, ...] = (
    'code_executor---shell_executor:curl *',
    'code_executor---shell_executor:wget *',
    'code_executor---shell_executor:ssh *',
    'code_executor---shell_executor:scp *',
    'code_executor---shell_executor:rsync *',
    'code_executor---shell_executor:nc *',
    'code_executor---shell_executor:netcat *',
)


@dataclass(frozen=True)
class PermissionConfig:
    """Top-level permission configuration from agent YAML."""
    mode: Literal['auto', 'strict', 'interactive'] = 'auto'
    whitelist: tuple[str, ...] = ()
    blacklist: tuple[str, ...] = _DEFAULT_BLACKLIST
    safety: SafetyConfig = SafetyConfig()

    @classmethod
    def from_dict(cls, d: dict[str, Any], project_root: str | None = None) -> PermissionConfig:
        if not d:
            return cls()

        raw_mode = d.get('mode', 'auto')
        _MODE_ALIASES = {'restricted': 'interactive'}
        mode = _MODE_ALIASES.get(raw_mode, raw_mode)
        whitelist = tuple(d.get('whitelist', ()))
        user_blacklist = tuple(d.get('blacklist', ()))
        blacklist = _DEFAULT_BLACKLIST + tuple(
            p for p in user_blacklist if p not in _DEFAULT_BLACKLIST
        )

        safety_raw = d.get('safety_rules', {})
        # Merge directory configs from top level into safety config
        for _dir_key in ('allowed_directories', 'read_only_directories'):
            if _dir_key in d and _dir_key not in safety_raw:
                safety_raw = dict(safety_raw)
                safety_raw[_dir_key] = d[_dir_key]
        if 'path_validation' in d and 'path_validation' not in safety_raw:
            safety_raw = dict(safety_raw)
            safety_raw['path_validation'] = d['path_validation']

        safety = SafetyConfig.from_dict(safety_raw, project_root=project_root)

        return cls(mode=mode, whitelist=whitelist, blacklist=blacklist, safety=safety)
