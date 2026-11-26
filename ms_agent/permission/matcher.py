"""Shared wildcard matching for permission rules.

Rule format: ``server---tool`` or ``server---tool:content_pattern``
Supports ``*`` / ``?`` wildcards via fnmatch, ``|`` to separate alternatives.
"""

from __future__ import annotations

import re
from typing import Any

from ms_agent.utils.pattern_matcher import match_pattern

TOOL_SPLITER = '---'
CONTENT_SEP = ':'


def _extract_content(tool_name: str, tool_args: dict[str, Any]) -> str | None:
    """Extract the primary content string from tool args for content-pattern matching."""
    val = None
    if tool_name.endswith(f'{TOOL_SPLITER}shell_executor'):
        val = tool_args.get('command')
    elif tool_name.endswith(f'{TOOL_SPLITER}write_file'):
        val = tool_args.get('path')
    elif tool_name.endswith(f'{TOOL_SPLITER}read_file'):
        val = tool_args.get('path')
    elif tool_name.endswith(f'{TOOL_SPLITER}edit_file'):
        val = tool_args.get('path')
    elif tool_name.endswith(f'{TOOL_SPLITER}grep'):
        val = tool_args.get('pattern')
    elif tool_name.endswith(f'{TOOL_SPLITER}glob'):
        val = tool_args.get('pattern')
    else:
        for key in ('path', 'command', 'query', 'url', 'pattern'):
            if key in tool_args:
                val = tool_args[key]
                break
    return str(val) if val is not None else None


def _with_bare_command_variants(content_pattern: str) -> str:
    """Add an argument-less variant for every ``<cmd> *`` alternative.

    ``curl *`` means "the curl command with any arguments" — and running it with
    NONE is a case of that. fnmatch disagrees: it wants the space and at least
    one character after it, so bare ``curl`` slipped past a rule written to gate
    exactly that, and a remembered ``whoami *`` failed to match the very
    ``whoami`` it was generated from.

    Only the space-star idiom of shell commands is extended. Path patterns end
    in ``/*`` (``~/.ssh/*``) or ``=*`` (``dd if=*``) and are left alone — there
    the trailing component is meaningful, not an optional argument list.
    """
    alts = [a.strip() for a in content_pattern.split('|')]
    out = list(alts)
    for alt in alts:
        if alt.endswith(' *'):
            out.append(alt[:-2].rstrip())
    return '|'.join(p for p in out if p)


# A compound shell line is a list of commands, not one big "content" string.
# These helpers turn it into the commands that actually run so a rule like
# ``curl *`` also gates a curl buried in a chain, pipeline, or wrapper.
_ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=')
_FIRST_TOKEN = re.compile(r'\s*(\S+)')
# Flags whose value is a separate token (drop the value along with the flag).
_WRAPPER_VALUE_FLAGS = frozenset({
    '-u',
    '--user',
    '--unset',
    '-g',
    '--group',
    '-p',
    '--prompt',
    '-S',
    '--split-string',
    '-C',
    '--chdir',
    '-P',
    '--path',
})


def _split_shell_command(command: str) -> list[str]:
    """Split on ``&&``, ``;``, ``|`` and newlines, ignoring quoted or escaped ones.

    A naive ``str.split`` would tear apart ``echo "a; b"``; a few characters of
    quote and escape tracking keep the operators that are really control flow.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(command):
        ch = command[i]
        if ch == '\\' and i + 1 < len(command):
            buf.append(command[i:i + 2])
            i += 2
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == '&' and command[i:i + 2] == '&&':
            segments.append(''.join(buf))
            buf = []
            i += 2
            continue
        if ch in (';', '|', '\n'):
            segments.append(''.join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append(''.join(buf))
    return [seg.strip() for seg in segments if seg.strip()]


def _strip_wrappers(command: str) -> str:
    """Drop leading ``env``/``sudo`` wrappers with their flags and assignments.

    ``env curl ...`` and ``sudo -u root curl ...`` both run curl; without this
    the first token is the wrapper and a ``curl *`` rule never sees the command.
    """
    tokens = command.split()
    while tokens and tokens[0] in ('env', 'sudo'):
        tokens = tokens[1:]
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == '--':
                i += 1
                break
            if _ASSIGNMENT.match(token):
                i += 1
                continue
            if token.startswith('-'):
                i += 1
                if token in _WRAPPER_VALUE_FLAGS and i < len(tokens):
                    i += 1
                continue
            break
        tokens = tokens[i:]
    return ' '.join(tokens)


def _basename_variants(command: str) -> list[str]:
    """Reduce a leading absolute executable path to its basename.

    ``/usr/bin/curl http://x`` must satisfy the same ``curl *`` rule as plain
    ``curl http://x`` — callers cannot be expected to spell out every prefix.
    """
    match = _FIRST_TOKEN.match(command)
    if not match:
        return []
    executable = match.group(1)
    if not executable.startswith('/') or '/' not in executable[1:]:
        return []
    basename = executable.rsplit('/', 1)[-1]
    if not basename:
        return []
    return [basename + command[match.end():]]


def _shell_command_variants(command: str) -> list[str]:
    """Return the original command plus normalized forms for rule matching.

    The original stays first, so rules written against a whole compound line
    (or a path/argument pattern) keep working. Every segment then contributes
    a wrapper-stripped form and an absolute-path-basename form.
    """
    variants = [command]
    for segment in _split_shell_command(command):
        variants.append(segment)
        normalized = _strip_wrappers(segment)
        if normalized and normalized != segment:
            variants.append(normalized)
        variants.extend(_basename_variants(normalized))
    return list(dict.fromkeys(v for v in variants if v))


class PermissionMatcher:
    """Wildcard matcher for permission rules, shared by both SafetyGuard and PermissionEnforcer."""

    def match(self, pattern: str, tool_call: str) -> bool:
        """Match a tool call string against a pattern using fnmatch.

        Supports ``|`` separated alternatives: ``read_file|write_file``.
        """
        return match_pattern(pattern, tool_call)

    def match_with_content(
        self,
        pattern: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> bool:
        """Match with optional content pattern after ``:``.

        Examples::

            "file_system---read_file"               → matches tool name only
            "code_executor---shell_executor:pip *"   → matches tool name + command content
            "file_system---*"                        → wildcard on tool name
        """
        if CONTENT_SEP in pattern:
            tool_pattern, content_pattern = pattern.split(CONTENT_SEP, 1)
        else:
            tool_pattern = pattern
            content_pattern = None

        if not self.match(tool_pattern, tool_name):
            return False

        if content_pattern is None:
            return True

        content = _extract_content(tool_name, tool_args)
        if content is None:
            return False

        pattern = _with_bare_command_variants(content_pattern)
        if tool_name.endswith(f'{TOOL_SPLITER}shell_executor'):
            # A shell "content" may be several commands chained together.
            # Match the rule against each command the line actually runs.
            return any(
                self.match(pattern, variant)
                for variant in _shell_command_variants(content))
        return self.match(pattern, content)
