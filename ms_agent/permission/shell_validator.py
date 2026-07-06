"""ShellPathValidator: path-level security analysis for shell commands.

Pipeline:
  1. Process substitution check
  2. Command substitution check ($(…) and backticks)
  3. Compound command splitting (&&, ||, ;, |, &, newlines)
  4. Per sub-command: wrapper strip → redirect check → path extract → path validate
  5. cd + write/create compound detection
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Literal, Sequence

from .path_extractors import (
    ExtractorEntry,
    build_extractor_registry,
    extract_find_exec_commands,
    find_uses_delete,
)
from .path_validator import (
    PathValidationResult,
    is_dangerous_removal_path,
    validate_path,
)
from .sed_validator import check_sed_expression_safety, is_sed_read_only
from .wrapper_strip import strip_safe_wrappers

_PROCESS_INPUT_SUB = re.compile(r'<\s*\(')
_PROCESS_OUTPUT_SUB = re.compile(r'>\s*\(')
_REDIRECT_PATTERN = re.compile(
    r'(?:&>>|&>|>>|>\||>)'
    r'\s*'
    r'(\S+)'
)
_FD_REDIRECT = re.compile(r'^\d*>&\d+$')
_MAX_SUBSTITUTION_DEPTH = 16


@dataclass(frozen=True)
class SafetyDecision:
    action: Literal['allow', 'deny', 'ask']
    reason: str
    category: str = ''


@dataclass(frozen=True)
class PathSafetyConfig:
    max_command_chars: int = 8192
    allowed_directories: tuple[str, ...] = ()
    read_only_directories: tuple[str, ...] = ()
    workspace_root: str | None = None


class ShellPathValidator:
    """Path-level security validator for shell_executor tool calls."""

    def __init__(
        self,
        allowed_dirs: Sequence[str],
        safety_config: PathSafetyConfig | None = None,
    ) -> None:
        self._allowed_dirs = list(allowed_dirs)
        self._config = safety_config or PathSafetyConfig()
        self._read_only_dirs = list(self._config.read_only_directories)
        self._workspace_root = self._config.workspace_root or os.getcwd()
        self._extractors = build_extractor_registry()

    def check(self, command: str, *, _depth: int = 0) -> SafetyDecision:
        if not command or not command.strip():
            return SafetyDecision(action='deny', reason='Empty shell command')

        if _depth > _MAX_SUBSTITUTION_DEPTH:
            return SafetyDecision(
                action='ask',
                reason='Command substitution nesting too deep',
                category='parse_failure',
            )

        if len(command) > self._config.max_command_chars:
            return SafetyDecision(
                action='deny',
                reason=f'Command exceeds max length ({self._config.max_command_chars})',
            )

        # 1. Process substitution
        if _PROCESS_OUTPUT_SUB.search(command):
            return SafetyDecision(
                action='ask',
                reason='Command contains output process substitution >(…) — may bypass path validation',
                category='process_output_sub',
            )
        if _PROCESS_INPUT_SUB.search(command):
            return SafetyDecision(
                action='ask',
                reason='Command contains input process substitution <(…) — cannot statically analyse',
                category='process_input_sub',
            )

        # 2. Command substitution — recursively validate inner commands
        substitution_result = self._check_command_substitutions(command, _depth=_depth)
        if substitution_result is not None:
            return substitution_result

        # 3. Split compound commands
        sub_commands = _split_compound(command)

        # Track cd presence for cd+write detection
        has_cd = False
        has_write_or_create = False

        for sub_cmd in sub_commands:
            try:
                tokens = shlex.split(sub_cmd)
            except ValueError:
                return SafetyDecision(action='ask', reason=f'Failed to parse command: {sub_cmd}', category='parse_failure')

            if not tokens:
                continue

            # 3. Check output redirections on the raw sub-command string
            redirect_result = self._check_redirects(sub_cmd)
            if redirect_result.action != 'allow':
                return redirect_result

            # 4. Strip safe wrappers
            tokens = strip_safe_wrappers(tokens)
            if not tokens:
                continue

            base_cmd = os.path.basename(tokens[0])
            args = tokens[1:]

            if base_cmd == 'cd':
                has_cd = True

            # 5. Command path extraction and validation
            result = self._check_command(base_cmd, args, _depth=_depth)
            if result.action != 'allow':
                return result

            entry = self._extractors.get(base_cmd)
            if entry and entry.op_type in ('write', 'create'):
                has_write_or_create = True

        # 6. cd + write/create compound → ask
        if has_cd and has_write_or_create:
            return SafetyDecision(
                action='ask',
                reason='Command combines cd with write/create operations — '
                       'path validation may not reflect runtime working directory',
                category='cd_write_compound',
            )

        return SafetyDecision(action='allow', reason='Shell command passed all checks')

    def _check_command_substitutions(
        self,
        command: str,
        *,
        _depth: int,
    ) -> SafetyDecision | None:
        try:
            bodies = _extract_command_substitutions(command)
        except ValueError as exc:
            return SafetyDecision(
                action='ask',
                reason=str(exc),
                category='parse_failure',
            )
        for inner in bodies:
            result = self.check(inner, _depth=_depth + 1)
            if result.action != 'allow':
                return result
        return None

    def _check_command(
        self,
        base_cmd: str,
        args: list[str],
        *,
        _depth: int = 0,
    ) -> SafetyDecision:
        entry = self._extractors.get(base_cmd)
        if entry is None:
            return SafetyDecision(action='allow', reason=f'Unregistered command: {base_cmd}')

        # Command-level validator (e.g. mv/cp with flags)
        if entry.command_validator is not None and base_cmd != 'find':
            err = entry.command_validator(args)
            if err:
                return SafetyDecision(action='ask', reason=err, category='command_validator')

        # sed special handling
        if base_cmd == 'sed':
            return self._check_sed(args, entry)

        if base_cmd == 'find':
            return self._check_find(args, entry, _depth=_depth)

        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(action='allow', reason=f'{base_cmd}: no paths to validate')

        return self._validate_paths(paths, entry.op_type, base_cmd)

    def _check_sed(self, args: list[str], entry: ExtractorEntry) -> SafetyDecision:
        op_type = entry.op_type
        if is_sed_read_only(args):
            op_type = 'read'

        # Expression safety check
        expressions = self._collect_sed_expressions(args)
        for expr in expressions:
            result = check_sed_expression_safety(expr)
            if not result.safe:
                return SafetyDecision(action='deny', reason=result.reason)

        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(action='allow', reason='sed: no file paths')

        return self._validate_paths(paths, op_type, 'sed')

    def _check_find(
        self,
        args: list[str],
        entry: ExtractorEntry,
        *,
        _depth: int,
    ) -> SafetyDecision:
        for exec_cmd in extract_find_exec_commands(args):
            result = self.check(exec_cmd, _depth=_depth + 1)
            if result.action != 'allow':
                return result

        if entry.command_validator is not None:
            err = entry.command_validator(args)
            if err:
                return SafetyDecision(action='ask', reason=err, category='command_validator')

        op_type = 'write' if find_uses_delete(args) else entry.op_type
        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(action='allow', reason='find: no paths to validate')

        return self._validate_paths(paths, op_type, 'find')

    @staticmethod
    def _collect_sed_expressions(args: list[str]) -> list[str]:
        expressions: list[str] = []
        skip_next = False
        script_found = False

        for i, arg in enumerate(args):
            if skip_next:
                skip_next = False
                continue
            if arg == '--':
                break
            if arg.startswith('-'):
                if arg in ('-e', '--expression'):
                    if i + 1 < len(args):
                        expressions.append(args[i + 1])
                        skip_next = True
                        script_found = True
                elif arg in ('-f', '--file'):
                    skip_next = True
                    script_found = True
                continue
            if not script_found:
                expressions.append(arg)
                script_found = True
        return expressions

    def _validate_paths(
        self,
        paths: list[str],
        op_type: Literal['read', 'write', 'create'],
        cmd_name: str,
    ) -> SafetyDecision:
        cwd = self._workspace_root

        for path in paths:
            # Dangerous removal check for rm/rmdir
            if cmd_name in ('rm', 'rmdir') and is_dangerous_removal_path(path):
                return SafetyDecision(
                    action='deny',
                    reason=f'Dangerous removal path: {path}',
                )

            result = validate_path(path, cwd, self._allowed_dirs, op_type, read_only_dirs=self._read_only_dirs)
            if not result.allowed:
                return SafetyDecision(action=result.action, reason=result.reason, category=result.category)

        return SafetyDecision(action='allow', reason=f'{cmd_name}: all paths validated')

    def _check_redirects(self, sub_cmd: str) -> SafetyDecision:
        for match in _REDIRECT_PATTERN.finditer(sub_cmd):
            target = match.group(1)
            if _FD_REDIRECT.match(target):
                continue
            if target == '/dev/null':
                continue
            if '$' in target or '%' in target:
                return SafetyDecision(
                    action='deny',
                    reason=f'Redirect target contains variable expansion: {target}',
                )

            result = validate_path(
                target, self._workspace_root, self._allowed_dirs, 'create',
                read_only_dirs=self._read_only_dirs,
            )
            if not result.allowed:
                return SafetyDecision(action=result.action, reason=result.reason, category=result.category)

        return SafetyDecision(action='allow', reason='Redirects OK')


def _extract_command_substitutions(command: str) -> list[str]:
    """Extract command bodies from ``$(…)`` and backticks outside single quotes."""
    bodies: list[str] = []
    i = 0
    chars = command
    in_single = False
    in_double = False

    while i < len(chars):
        c = chars[i]

        if c == '\\' and not in_single and i + 1 < len(chars):
            i += 2
            continue

        if c == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if c == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if in_single:
            i += 1
            continue

        if c == '$' and i + 1 < len(chars):
            if chars[i + 1] == '{':
                body, end = _read_brace_expansion(chars, i + 2)
                if body is None:
                    raise ValueError('Unclosed parameter expansion in command substitution')
                bodies.extend(_extract_command_substitutions(body))
                i = end
                continue
            if chars[i + 1] == '(':
                if i + 2 < len(chars) and chars[i + 2] == '(':
                    body, end = _read_delimited_body(chars, i + 3, '(', ')')
                    if body is None:
                        raise ValueError('Unclosed arithmetic expansion in command')
                    i = end
                    continue
                body, end = _read_delimited_body(chars, i + 2, '(', ')')
                if body is None:
                    raise ValueError('Unclosed command substitution $(…)')
                bodies.append(body)
                bodies.extend(_extract_command_substitutions(body))
                i = end
                continue

        if c == '`':
            body, end = _read_backtick_body(chars, i + 1)
            if body is None:
                raise ValueError('Unclosed backtick command substitution')
            bodies.append(body)
            bodies.extend(_extract_command_substitutions(body))
            i = end
            continue

        i += 1

    return bodies


def _read_delimited_body(
    command: str,
    start: int,
    open_char: str,
    close_char: str,
) -> tuple[str | None, int]:
    depth = 1
    i = start
    in_single = False
    in_double = False

    while i < len(command):
        c = command[i]

        if c == '\\' and not in_single and i + 1 < len(command):
            i += 2
            continue

        if c == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if c == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if in_single or in_double:
            i += 1
            continue

        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return command[start:i], i + 1

        i += 1

    return None, start


def _read_brace_expansion(command: str, start: int) -> tuple[str | None, int]:
    depth = 1
    i = start
    in_single = False
    in_double = False

    while i < len(command):
        c = command[i]

        if c == '\\' and not in_single and i + 1 < len(command):
            i += 2
            continue

        if c == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue

        if c == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue

        if in_single or in_double:
            i += 1
            continue

        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return command[start:i], i + 1

        i += 1

    return None, start


def _read_backtick_body(command: str, start: int) -> tuple[str | None, int]:
    i = start
    while i < len(command):
        c = command[i]
        if c == '\\' and i + 1 < len(command):
            i += 2
            continue
        if c == '`':
            return command[start:i], i + 1
        i += 1
    return None, start


def _split_compound(command: str) -> list[str]:
    """Split a compound command on shell command separators.

    Splits on ``&&``, ``||``, ``;``, ``|``, single ``&``, and newlines.
    Does not split inside quotes.
    """
    parts: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    chars = command

    while i < len(chars):
        c = chars[i]

        if c == '\\' and not in_single and i + 1 < len(chars):
            current.append(c)
            current.append(chars[i + 1])
            i += 2
            continue

        if c == "'" and not in_double:
            in_single = not in_single
            current.append(c)
            i += 1
            continue

        if c == '"' and not in_single:
            in_double = not in_double
            current.append(c)
            i += 1
            continue

        if in_single or in_double:
            current.append(c)
            i += 1
            continue

        # Check for compound operators
        if c in '\n\r':
            parts.append(''.join(current).strip())
            current = []
            i += 1
            if c == '\r' and i < len(chars) and chars[i] == '\n':
                i += 1
            continue
        if c == ';':
            parts.append(''.join(current).strip())
            current = []
            i += 1
            continue
        if c == '|':
            if i + 1 < len(chars) and chars[i + 1] == '|':
                parts.append(''.join(current).strip())
                current = []
                i += 2
                continue
            parts.append(''.join(current).strip())
            current = []
            i += 1
            continue
        if c == '&':
            if i + 1 < len(chars) and chars[i + 1] == '&':
                parts.append(''.join(current).strip())
                current = []
                i += 2
                continue
            parts.append(''.join(current).strip())
            current = []
            i += 1
            continue

        current.append(c)
        i += 1

    remainder = ''.join(current).strip()
    if remainder:
        parts.append(remainder)

    return [p for p in parts if p]
