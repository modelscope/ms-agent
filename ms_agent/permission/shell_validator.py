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
from pathlib import Path
from typing import Literal, Sequence

from .path_extractors import (INTERPRETER_COMMANDS, ExtractorEntry,
                              build_extractor_registry,
                              extract_find_exec_commands,
                              extract_interpreter_script, find_uses_delete,
                              interpreter_runs_inline_code)
from .path_validator import (PathValidationResult, is_dangerous_removal_path,
                             validate_path)
from .sed_validator import check_sed_expression_safety, is_sed_read_only
from .wrapper_strip import strip_safe_wrappers

_PROCESS_INPUT_SUB = re.compile(r'<\s*\(')
_PROCESS_OUTPUT_SUB = re.compile(r'>\s*\(')
_FD_REDIRECT = re.compile(r'^\d*>&\d+$')
_MAX_SUBSTITUTION_DEPTH = 16

#: Character devices every shell uses as a sink or a source. They are not
#: files the workspace policy has anything to say about.
_REDIRECT_DEVICE_ALLOWLIST = frozenset({
    '/dev/null',
    '/dev/stdout',
    '/dev/stderr',
    '/dev/stdin',
    '/dev/tty',
    '/dev/zero',
})

#: Ends a word in shell source. Used to know where a redirect target stops —
#: notably at the `)` closing a subshell, which is not part of the filename.
_WORD_TERMINATORS = frozenset(' \t\n\r;|&()<>')


def _extract_redirect_targets(command: str) -> list[str]:
    """Find the target of every output redirection in one command.

    Walks the source tracking quote state instead of pattern-matching it. A
    regex reading ``\\S+`` after the operator cannot see either boundary that
    matters: it takes ``>`` inside a quoted argument for a redirection
    (``git commit -m "a > b"``), and it swallows whatever punctuation abuts the
    filename, so ``(… 2>/dev/null)`` yields the target ``/dev/null)`` — which
    matches no allowlist entry and gets refused as a write outside the
    workspace.
    """
    targets: list[str] = []
    i = 0
    n = len(command)
    in_single = False
    in_double = False

    while i < n:
        c = command[i]

        if c == '\\' and not in_single and i + 1 < n:
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

        if c != '>':
            i += 1
            continue

        # Step back over an fd prefix (``2>``) and ``&`` of ``&>``.
        start = i
        i += 1
        if i < n and command[i] == '>':  # >>
            i += 1
        elif i < n and command[i] == '|':  # >|
            i += 1
        elif i < n and command[i] == '&':
            # ``>&2`` / ``2>&1`` duplicates a descriptor; no file involved.
            j = i + 1
            while j < n and command[j].isdigit():
                j += 1
            if j > i + 1 or (j < n and command[j] == '-'):
                i = j
                continue

        while i < n and command[i] in ' \t':
            i += 1

        word_start = i
        word: list[str] = []
        w_single = False
        w_double = False
        while i < n:
            ch = command[i]
            if ch == '\\' and not w_single and i + 1 < n:
                word.append(command[i + 1])
                i += 2
                continue
            if ch == "'" and not w_double:
                w_single = not w_single
                i += 1
                continue
            if ch == '"' and not w_single:
                w_double = not w_double
                i += 1
                continue
            if not w_single and not w_double and ch in _WORD_TERMINATORS:
                break
            word.append(ch)
            i += 1

        if i == word_start and not word:
            # A bare ``>`` with nothing after it — malformed, but not ours to
            # interpret; leave it to the shell.
            del start
            continue
        targets.append(''.join(word))

    return targets


_REDIRECT_TOKEN = re.compile(r'^\d*(?:&?>>?\|?|<<?<?|>&|<&)$')


def _strip_redirections(tokens: list[str]) -> list[str]:
    """Remove redirection operators and their targets from a token list.

    ``shlex.split`` has no idea ``>`` means anything, so ``ls >> /dev/null``
    arrives as three plain words and the extractor reads ``/dev/null`` as a
    file ``ls`` was asked to list. Redirect targets are checked separately, by
    :func:`_extract_redirect_targets`, against the rules for the write they
    actually are.
    """
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if _FD_REDIRECT.match(token):
            i += 1
            continue
        if _REDIRECT_TOKEN.match(token):
            # Operator and, unless it is a descriptor duplication, its target.
            i += 1
            if i < len(tokens) and not _REDIRECT_TOKEN.match(tokens[i]):
                i += 1
            continue
        # Glued forms such as ``2>/dev/null`` or ``>out.txt``.
        glued = re.match(r'^\d*(?:&?>>?\|?|<<?<?)(?=\S)', token)
        if glued:
            i += 1
            continue
        out.append(token)
        i += 1
    return out


def _unwrap_group(sub_cmd: str) -> str:
    """Peel subshell/command-group punctuation off one sub-command.

    Splitting a compound command on its operators leaves the delimiters of any
    group attached to the neighbouring word — ``(cd sub && ls)`` yields
    ``(cd sub`` and ``ls)``. Only unquoted leading/trailing delimiters are
    removed, so a real argument like ``echo "(hi)"`` is untouched.
    """
    out = sub_cmd.strip()
    while out and out[0] in '({':
        out = out[1:].lstrip()
    while out and out[-1] in ')}':
        out = out[:-1].rstrip()
        if out.endswith(';'):
            out = out[:-1].rstrip()
    return out


_HEREDOC_START = re.compile(r'<<-?\s*([\'"]?)([A-Za-z_][A-Za-z0-9_]*)\1')


def _strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc payloads, keeping the command lines that introduce them.

    A heredoc body is DATA. Left in place it is split on newlines like any
    compound command and each line analysed as if it were one, so a line of
    Python such as ``result = [x * 2 for x in data if x > 1]`` reads as a
    redirection into a file named ``1]`` — a glob in a create position, and a
    refusal for a script that touches nothing.
    """
    if '<<' not in command:
        return command

    lines = command.splitlines()
    kept: list[str] = []
    pending: list[tuple] = []
    opener_at: int = -1  # where the still-open heredoc began, on kept[-1]

    for line in lines:
        if pending:
            delimiter, strip_tabs = pending[0]
            candidate = line.lstrip('\t') if strip_tabs else line
            if candidate.strip() == delimiter:
                pending.pop(0)
                if not pending:
                    opener_at = -1
            continue

        kept.append(line)
        for match in _HEREDOC_START.finditer(line):
            if not pending:
                opener_at = match.start()
            pending.append((match.group(2), match.group(0).startswith('<<-')))

    if pending and kept and opener_at >= 0:
        # Opened and never closed. The shell will reject this outright, so
        # there is nothing here to judge — and judging it anyway means reading
        # the payload as filenames and refusing for a reason that is not true.
        # Seen when a multi-line command reaches us flattened onto one line
        # (a paste that lost its newlines): the refusal claimed a "glob in a
        # create operation" for a script that creates nothing, hiding the
        # actual problem, which is a syntax error.
        kept[-1] = kept[-1][:opener_at].rstrip()

    return '\n'.join(kept)


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
    dangerous_removal_paths: tuple[str, ...] = ()
    sensitive_read_paths: tuple[str, ...] = ()


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
        self._sensitive_read_paths = list(self._config.sensitive_read_paths)
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
                reason=
                f'Command exceeds max length ({self._config.max_command_chars})',
            )

        # Heredoc payloads are data, not commands. Analysing them as commands
        # is how an inline Python script gets refused for a "glob in a create
        # operation" it never contained.
        command = _strip_heredoc_bodies(command)

        # 1. Process substitution
        if _PROCESS_OUTPUT_SUB.search(command):
            return SafetyDecision(
                action='ask',
                reason=
                'Command contains output process substitution >(…) — may bypass path validation',
                category='process_output_sub',
            )
        if _PROCESS_INPUT_SUB.search(command):
            return SafetyDecision(
                action='ask',
                reason=
                'Command contains input process substitution <(…) — cannot statically analyse',
                category='process_input_sub',
            )

        # 2. Command substitution — recursively validate inner commands
        substitution_result = self._check_command_substitutions(
            command, _depth=_depth)
        if substitution_result is not None:
            return substitution_result

        # 3. Split compound commands
        sub_commands = _split_compound(command)

        # Track cwd through cd commands for accurate path validation
        _current_cwd = self._workspace_root

        for sub_cmd in sub_commands:
            # Strip comment lines (starting with #) before parsing
            stripped = sub_cmd.strip()
            if stripped.startswith('#'):
                continue  # Skip pure comment

            # Unwrap subshell / group punctuation so the first token is the
            # command. Without this `(cd sub && …)` presents `(cd` as the
            # command name, which matches no extractor and silently skips the
            # cd tracking the rest of the loop depends on.
            stripped = _unwrap_group(stripped)
            if not stripped or stripped.startswith('#'):
                continue
            sub_cmd = stripped

            try:
                tokens = shlex.split(sub_cmd)
            except ValueError:
                return SafetyDecision(
                    action='ask',
                    reason=f'Failed to parse command: {sub_cmd}',
                    category='parse_failure')

            if not tokens:
                continue

            # 3. Check output redirections on the raw sub-command string
            redirect_result = self._check_redirects(sub_cmd)
            if redirect_result.action != 'allow':
                return redirect_result

            # 4. Strip safe wrappers and redirection syntax
            tokens = _strip_redirections(tokens)
            tokens = strip_safe_wrappers(tokens)
            if not tokens:
                continue

            base_cmd = os.path.basename(tokens[0])
            args = tokens[1:]

            # Track cd: resolve target and update _current_cwd
            if base_cmd == 'cd':
                cd_entry = self._extractors.get('cd')
                if cd_entry:
                    cd_targets = cd_entry.extractor(args)
                    if cd_targets:
                        target = cd_targets[0]
                        if os.path.isabs(target):
                            _current_cwd = str(Path(target).resolve())
                        else:
                            _current_cwd = str(
                                (Path(_current_cwd) / target).resolve())

            # 5. Command path extraction and validation
            result = self._check_command(
                base_cmd, args, _depth=_depth, cwd=_current_cwd)
            if result.action != 'allow':
                return result

        return SafetyDecision(
            action='allow', reason='Shell command passed all checks')

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
        cwd: str | None = None,
    ) -> SafetyDecision:
        if base_cmd in INTERPRETER_COMMANDS:
            return self._check_interpreter(base_cmd, args, cwd=cwd)

        entry = self._extractors.get(base_cmd)
        if entry is None:
            return SafetyDecision(
                action='allow', reason=f'Unregistered command: {base_cmd}')

        # Command-level validator (e.g. mv/cp with flags)
        if entry.command_validator is not None and base_cmd != 'find':
            err = entry.command_validator(args)
            if err:
                return SafetyDecision(
                    action='ask', reason=err, category='command_validator')

        # sed special handling
        if base_cmd == 'sed':
            return self._check_sed(args, entry, cwd=cwd)

        if base_cmd == 'find':
            return self._check_find(args, entry, _depth=_depth, cwd=cwd)

        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(
                action='allow', reason=f'{base_cmd}: no paths to validate')

        return self._validate_paths(paths, entry.op_type, base_cmd, cwd=cwd)

    def _check_interpreter(self,
                           base_cmd: str,
                           args: list[str],
                           *,
                           cwd: str | None = None) -> SafetyDecision:
        """Judge a command that runs code rather than touching named files.

        Pointing an interpreter at a script inside the workspace is the same
        kind of act as reading that script, and is treated that way — otherwise
        every ``python3 build.py`` in a normal project would need confirming,
        and a prompt nobody can act on is a prompt everybody clicks through.
        Code arriving inline or on stdin has no path to judge, so it is raised
        for the mode to resolve.
        """
        if not interpreter_runs_inline_code(args):
            script = extract_interpreter_script(args)
            if script:
                result = self._validate_paths(
                    script, 'read', base_cmd, cwd=cwd)
                if result.action != 'allow':
                    return result
                return SafetyDecision(
                    action='allow',
                    reason=f'{base_cmd}: runs a script inside allowed dirs',
                )

        return SafetyDecision(
            action='ask',
            reason=(f'`{base_cmd}` runs code given inline or on stdin; what it '
                    'touches cannot be determined from the command'),
            category='interpreter_exec',
        )

    def _check_sed(self,
                   args: list[str],
                   entry: ExtractorEntry,
                   *,
                   cwd: str | None = None) -> SafetyDecision:
        op_type = entry.op_type
        if is_sed_read_only(args):
            op_type = 'read'

        # Expression safety check
        expressions = self._collect_sed_expressions(args)
        for expr in expressions:
            result = check_sed_expression_safety(expr)
            if not result.safe:
                return SafetyDecision(action='ask', reason=result.reason)

        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(action='allow', reason='sed: no file paths')

        return self._validate_paths(paths, op_type, 'sed', cwd=cwd)

    def _check_find(
        self,
        args: list[str],
        entry: ExtractorEntry,
        *,
        _depth: int,
        cwd: str | None = None,
    ) -> SafetyDecision:
        for exec_cmd in extract_find_exec_commands(args):
            result = self.check(exec_cmd, _depth=_depth + 1)
            if result.action != 'allow':
                return result

        if entry.command_validator is not None:
            err = entry.command_validator(args)
            if err:
                return SafetyDecision(
                    action='ask', reason=err, category='command_validator')

        op_type = 'write' if find_uses_delete(args) else entry.op_type
        paths = entry.extractor(args)
        if not paths:
            return SafetyDecision(
                action='allow', reason='find: no paths to validate')

        return self._validate_paths(paths, op_type, 'find', cwd=cwd)

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
        *,
        cwd: str | None = None,
    ) -> SafetyDecision:
        effective_cwd = cwd or self._workspace_root

        for path in paths:
            # Dangerous removal check for rm/rmdir
            if cmd_name in ('rm', 'rmdir') and is_dangerous_removal_path(
                    path, self._config.dangerous_removal_paths):
                return SafetyDecision(
                    action='deny',
                    reason=f'Dangerous removal path: {path}',
                )

            result = validate_path(
                path,
                effective_cwd,
                self._allowed_dirs,
                op_type,
                read_only_dirs=self._read_only_dirs,
                sensitive_paths=self._sensitive_read_paths)
            if not result.allowed:
                return SafetyDecision(
                    action=result.action,
                    reason=result.reason,
                    category=result.category)

        return SafetyDecision(
            action='allow', reason=f'{cmd_name}: all paths validated')

    def _check_redirects(self, sub_cmd: str) -> SafetyDecision:
        for target in _extract_redirect_targets(sub_cmd):
            if not target:
                continue
            if _FD_REDIRECT.match(target):
                continue
            if target in _REDIRECT_DEVICE_ALLOWLIST:
                continue
            if '$' in target or '%' in target:
                return SafetyDecision(
                    action='deny',
                    reason=
                    f'Redirect target contains variable expansion: {target}',
                )

            result = validate_path(
                target,
                self._workspace_root,
                self._allowed_dirs,
                'create',
                read_only_dirs=self._read_only_dirs,
                sensitive_paths=self._sensitive_read_paths,
            )
            if not result.allowed:
                return SafetyDecision(
                    action=result.action,
                    reason=result.reason,
                    category=result.category)

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
                    raise ValueError(
                        'Unclosed parameter expansion in command substitution')
                bodies.extend(_extract_command_substitutions(body))
                i = end
                continue
            if chars[i + 1] == '(':
                if i + 2 < len(chars) and chars[i + 2] == '(':
                    body, end = _read_delimited_body(chars, i + 3, '(', ')')
                    if body is None:
                        raise ValueError(
                            'Unclosed arithmetic expansion in command')
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
