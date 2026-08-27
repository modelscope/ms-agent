"""Configuration parsing for the permission module.

Reads the ``permission`` section from agent YAML and produces frozen
dataclasses consumed by SafetyGuard and PermissionEnforcer.
"""

from __future__ import annotations

import os
from pathlib import Path
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

#: Locations whose CONTENTS are a credential. Kept apart from
#: ``sensitive_paths`` because the two lists answer different questions:
#: that one protects things from being CHANGED (``.git/config``,
#: ``~/.bashrc``), which is no reason to refuse reading them — an agent that
#: cannot run ``cat .git/config`` to find a remote is just broken. These are
#: things that must not be COPIED, most of all into a transcript that gets
#: written to disk and replayed to a model.
#:
#: Patterns are fnmatch, where ``*`` crosses ``/``, so a leading ``*/`` covers
#: any user's home rather than only the one the process happens to run as.
_DEFAULT_SENSITIVE_READ_PATHS: tuple[str, ...] = (
    '*/.ssh/*',
    '*/.gnupg/*',
    '*/.aws/*',
    '*/.kube/config',
    '*/.docker/config.json',
    '*/.netrc',
    '*/id_rsa',
    '*/id_dsa',
    '*/id_ecdsa',
    '*/id_ed25519',
    '*/*.pem',
)

_DEFAULT_DANGEROUS_REMOVAL: tuple[str, ...] = (
    '*',
    '/*',
    '/',
    '~',
)


def default_temp_directories() -> tuple[str, ...]:
    """Scratch directories the agent may write to besides its workspace.

    Refusing these buys nothing: the OS temp directory is world-writable by
    design and holds nothing to protect. It costs plenty, though — every tool
    that stages output through a temp file, and every ``python3 - <<EOF`` the
    agent would rather write to a real file first, comes back refused. Both
    spellings are listed because ``TMPDIR`` and a literal ``/tmp`` are
    different paths on macOS, and either may be what a command actually uses.

    Turn off with ``permission.safety_rules.allow_temp_dir: false``.
    """
    import tempfile

    out: list[str] = []
    for raw in (tempfile.gettempdir(), '/tmp'):
        if not raw:
            continue
        try:
            resolved = str(Path(raw).resolve())
        except OSError:
            continue
        if resolved not in out:
            out.append(resolved)
    return tuple(out)


@dataclass(frozen=True)
class SafetyConfig:
    """Inner-layer safety configuration (non-bypassable)."""
    patterns: tuple[str, ...] = _DEFAULT_SAFETY_PATTERNS
    sensitive_paths: tuple[str, ...] = _DEFAULT_SENSITIVE_PATHS
    sensitive_read_paths: tuple[str, ...] = _DEFAULT_SENSITIVE_READ_PATHS
    dangerous_removal_paths: tuple[str, ...] = _DEFAULT_DANGEROUS_REMOVAL
    read_policy: Literal['loose', 'strict'] = 'loose'
    max_command_chars: int = 8192
    allowed_directories: tuple[str, ...] = ()
    read_only_directories: tuple[str, ...] = ()
    allow_temp_dir: bool = True

    @classmethod
    def from_dict(cls,
                  d: dict[str, Any],
                  project_root: str | None = None) -> SafetyConfig:
        patterns = tuple(d.get('patterns', _DEFAULT_SAFETY_PATTERNS))
        sensitive = tuple(d.get('sensitive_paths', _DEFAULT_SENSITIVE_PATHS))
        sensitive_read = tuple(
            d.get('sensitive_read_paths', _DEFAULT_SENSITIVE_READ_PATHS))
        dangerous = tuple(
            d.get('dangerous_removal_paths', _DEFAULT_DANGEROUS_REMOVAL))

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
            sensitive_read_paths=sensitive_read,
            dangerous_removal_paths=dangerous,
            read_policy=read_policy,
            max_command_chars=max_chars,
            allowed_directories=allowed,
            read_only_directories=read_only,
            allow_temp_dir=bool(d.get('allow_temp_dir', True)),
        )

    def effective_allowed_directories(
            self, workspace_root: str) -> tuple[str, ...]:
        """Every directory writes are permitted in, workspace root first."""
        out = [workspace_root]
        for directory in self.allowed_directories:
            if directory not in out:
                out.append(directory)
        if self.allow_temp_dir:
            for directory in default_temp_directories():
                if directory not in out:
                    out.append(directory)
        return tuple(out)


#: Nothing by default. A blacklist entry can never be overridden — not by the
#: mode, not by a whitelist, not by the user answering a prompt — so it is the
#: wrong tool for "risky, ask first". The network-egress commands below used to
#: live here and were simply unusable: an agent asked to run ``curl`` reported
#: that it had been blocked and there was no way for the user to permit it.
_DEFAULT_BLACKLIST: tuple[str, ...] = ()

#: Commands that must be CONFIRMED rather than refused. Unlike the mode-level
#: default these hold in every mode, including full-access: reaching the network
#: or another host is worth one deliberate click even from a user who has
#: otherwise waved the agent through. ``allow_network: true`` drops them.
_DEFAULT_ASK_RULES: tuple[str, ...] = (
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
    # Defaulted here as well as in from_dict: a config with no ``permission``
    # section at all takes the early return below, and the network commands
    # must still be confirmed there.
    ask_rules: tuple[str, ...] = _DEFAULT_ASK_RULES
    safety: SafetyConfig = SafetyConfig()

    @classmethod
    def from_dict(cls,
                  d: dict[str, Any],
                  project_root: str | None = None) -> PermissionConfig:
        if not d:
            return cls()

        raw_mode = d.get('mode', 'auto')
        _MODE_ALIASES = {'restricted': 'interactive'}
        mode = _MODE_ALIASES.get(raw_mode, raw_mode)
        whitelist = tuple(d.get('whitelist', ()))
        user_ask_rules = tuple(d.get('ask_rules', ()))
        user_blacklist = tuple(d.get('blacklist', ()))
        # Network-egress shell commands (curl/wget/ssh/...) are confirmed, not
        # refused. ``allow_network: true`` (or legacy ``no_default_blacklist``)
        # opts out of that confirmation; the user's own rules still apply.
        allow_network = bool(
            d.get('allow_network', False)
            or d.get('no_default_blacklist', False))
        base_ask = () if allow_network else _DEFAULT_ASK_RULES
        ask_rules = base_ask + tuple(
            p for p in user_ask_rules if p not in base_ask)
        blacklist = _DEFAULT_BLACKLIST + tuple(
            p for p in user_blacklist if p not in _DEFAULT_BLACKLIST)

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

        return cls(
            mode=mode,
            whitelist=whitelist,
            blacklist=blacklist,
            ask_rules=ask_rules,
            safety=safety,
        )
