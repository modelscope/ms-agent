"""PATH_EXTRACTORS registry: per-command path extraction for shell commands.

Five extraction strategies:
  A) filter_out_flags — 27 commands
  B) parse_pattern_command — grep, rg
  C) special arg skip — sed, jq
  D) search-start collection — find
  E) subcommand dispatch — git
  Special — cd, ls, tr
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Literal

CommandExtractor = Callable[[list[str]], list[str]]
CommandValidator = Callable[[list[str]], str | None]


@dataclass(frozen=True)
class ExtractorEntry:
    extractor: CommandExtractor
    op_type: Literal['read', 'write', 'create']
    description: str
    command_validator: CommandValidator | None = None


# ---------------------------------------------------------------------------
# Strategy A: filter_out_flags
# ---------------------------------------------------------------------------

def filter_out_flags(args: list[str]) -> list[str]:
    """Keep non-flag arguments, respecting ``--`` separator."""
    result: list[str] = []
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            result.append(arg)
        elif arg == '--':
            after_double_dash = True
        elif not arg.startswith('-'):
            result.append(arg)
    return result


# ---------------------------------------------------------------------------
# Strategy B: parse_pattern_command (grep / rg)
# ---------------------------------------------------------------------------

def parse_pattern_command(
    args: list[str],
    flags_with_args: set[str],
    defaults: list[str] | None = None,
) -> list[str]:
    """Extract file paths from pattern-based commands (grep/rg).

    First non-flag arg is the search pattern (skipped); rest are file paths.
    If ``-e``/``-f`` explicitly provides the pattern, all non-flag args are paths.
    """
    paths: list[str] = []
    pattern_found = False
    after_double_dash = False

    i = 0
    while i < len(args):
        arg = args[i]
        if after_double_dash:
            paths.append(arg)
            i += 1
            continue
        if arg == '--':
            after_double_dash = True
            i += 1
            continue
        if arg.startswith('-'):
            flag = arg.split('=')[0]
            if flag in ('-e', '--regexp', '-f', '--file'):
                pattern_found = True
            if flag in flags_with_args and '=' not in arg:
                i += 1  # skip flag value
            i += 1
            continue
        if not pattern_found:
            pattern_found = True
            i += 1
            continue  # skip the pattern itself
        paths.append(arg)
        i += 1
    return paths if paths else (defaults or [])


# ---------------------------------------------------------------------------
# Strategy C: special arg skip (sed / jq)
# ---------------------------------------------------------------------------

def extract_sed(args: list[str]) -> list[str]:
    """Extract file paths from sed, skipping expression arguments."""
    paths: list[str] = []
    skip_next = False
    script_found = False
    after_dd = False

    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if not after_dd and arg == '--':
            after_dd = True
            continue
        if not after_dd and arg.startswith('-'):
            if arg in ('-f', '--file'):
                if i + 1 < len(args):
                    paths.append(args[i + 1])
                    skip_next = True
                script_found = True
            elif arg in ('-e', '--expression'):
                skip_next = True
                script_found = True
            elif 'e' in arg[1:] or 'f' in arg[1:]:
                script_found = True
            continue
        if not script_found:
            script_found = True
            continue  # skip inline expression
        paths.append(arg)
    return paths


_JQ_FLAGS_WITH_ARGS = frozenset({
    '-f', '--from-file', '--arg', '--argjson', '--slurpfile',
    '--rawfile', '-L', '--indent', '--jsonargs', '--args',
})


def extract_jq(args: list[str]) -> list[str]:
    """Extract file paths from jq, skipping filter expression."""
    paths: list[str] = []
    filter_found = False
    after_double_dash = False

    i = 0
    while i < len(args):
        arg = args[i]
        if after_double_dash:
            paths.append(arg)
            i += 1
            continue
        if arg == '--':
            after_double_dash = True
            i += 1
            continue
        if arg.startswith('-'):
            flag = arg.split('=')[0]
            if flag in _JQ_FLAGS_WITH_ARGS and '=' not in arg:
                i += 1
            i += 1
            continue
        if not filter_found:
            filter_found = True
            i += 1
            continue  # skip the filter
        paths.append(arg)
        i += 1
    return paths


# ---------------------------------------------------------------------------
# Strategy D: search-start collection (find)
# ---------------------------------------------------------------------------

_FIND_PATH_FLAGS = frozenset({
    '-newer', '-anewer', '-cnewer', '-mnewer', '-samefile',
    '-path', '-wholename', '-ilname', '-lname', '-ipath', '-iwholename',
})
_FIND_NEWER_PATTERN = re.compile(r'^-newer[acmBt][acmtB]$')


def extract_find(args: list[str]) -> list[str]:
    """Extract search starting points and path-valued flags from find."""
    paths: list[str] = []
    found_non_global_flag = False
    after_double_dash = False

    i = 0
    while i < len(args):
        arg = args[i]
        if after_double_dash:
            paths.append(arg)
            i += 1
            continue
        if arg == '--':
            after_double_dash = True
            i += 1
            continue
        if arg.startswith('-'):
            if arg in ('-H', '-L', '-P'):
                i += 1
                continue
            found_non_global_flag = True
            if arg in _FIND_PATH_FLAGS or _FIND_NEWER_PATTERN.match(arg):
                if i + 1 < len(args):
                    paths.append(args[i + 1])
                    i += 1
            i += 1
            continue
        if not found_non_global_flag:
            paths.append(arg)
        i += 1
    return paths if paths else ['.']


# ---------------------------------------------------------------------------
# Strategy E: subcommand dispatch (git)
# ---------------------------------------------------------------------------

def extract_git(args: list[str]) -> list[str]:
    """Extract paths only for ``git diff --no-index``."""
    if args and args[0] == 'diff' and '--no-index' in args:
        return filter_out_flags(args[1:])[:2]
    return []


# ---------------------------------------------------------------------------
# Special commands: cd, ls, tr
# ---------------------------------------------------------------------------

def extract_cd(args: list[str]) -> list[str]:
    if not args:
        return [os.path.expanduser('~')]
    return [' '.join(args)]


def extract_ls(args: list[str]) -> list[str]:
    paths = filter_out_flags(args)
    return paths if paths else ['.']


def extract_tr(args: list[str]) -> list[str]:
    has_delete = any(
        a == '-d' or a == '--delete' or (a.startswith('-') and 'd' in a[1:])
        for a in args
    )
    non_flags = filter_out_flags(args)
    skip_count = 1 if has_delete else 2
    return non_flags[skip_count:]


# ---------------------------------------------------------------------------
# grep / rg specific flag sets
# ---------------------------------------------------------------------------

_GREP_FLAGS_WITH_ARGS = frozenset({
    '-e', '--regexp', '-f', '--file',
    '--exclude', '--include', '--exclude-dir', '--include-dir',
    '-m', '--max-count',
    '-A', '--after-context', '-B', '--before-context', '-C', '--context',
    '--label', '--color',
})

_RG_FLAGS_WITH_ARGS = frozenset({
    '-e', '--regexp', '-f', '--file',
    '-t', '--type', '-T', '--type-not',
    '-g', '--glob', '-m', '--max-count', '--max-depth',
    '-r', '--replace',
    '-A', '--after-context', '-B', '--before-context', '-C', '--context',
    '--color', '--colors', '--encoding', '-E',
    '--iglob', '--type-add', '--type-clear',
})


def _extract_grep(args: list[str]) -> list[str]:
    has_recursive = any(a in ('-r', '-R', '--recursive') for a in args)
    paths = parse_pattern_command(args, _GREP_FLAGS_WITH_ARGS)
    if not paths and has_recursive:
        return ['.']
    return paths


def _extract_rg(args: list[str]) -> list[str]:
    return parse_pattern_command(args, _RG_FLAGS_WITH_ARGS, defaults=['.'])


# ---------------------------------------------------------------------------
# Command validators (mv / cp)
# ---------------------------------------------------------------------------

def _validate_mv_cp(args: list[str]) -> str | None:
    """Reject mv/cp calls with flags (--target-directory bypass risk)."""
    for arg in args:
        if arg == '--':
            break
        if arg.startswith('-'):
            return f'mv/cp with flags requires confirmation (possible --target-directory bypass)'
    return None


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

def _make_filter_entry(
    op_type: Literal['read', 'write', 'create'],
    description: str,
    *,
    validator: CommandValidator | None = None,
) -> ExtractorEntry:
    return ExtractorEntry(
        extractor=filter_out_flags,
        op_type=op_type,
        description=description,
        command_validator=validator,
    )


def build_extractor_registry() -> dict[str, ExtractorEntry]:
    """Build the full 34-command extractor registry."""
    registry: dict[str, ExtractorEntry] = {}

    # Special commands
    registry['cd'] = ExtractorEntry(extract_cd, 'read', 'change directories to')
    registry['ls'] = ExtractorEntry(extract_ls, 'read', 'list files in')
    registry['tr'] = ExtractorEntry(extract_tr, 'read', 'transform text from files in')

    # Strategy D
    registry['find'] = ExtractorEntry(extract_find, 'read', 'search files in')

    # Strategy B
    registry['grep'] = ExtractorEntry(_extract_grep, 'read', 'search for patterns in files from')
    registry['rg'] = ExtractorEntry(_extract_rg, 'read', 'search for patterns in files from')

    # Strategy C
    registry['sed'] = ExtractorEntry(extract_sed, 'write', 'edit files in')
    registry['jq'] = ExtractorEntry(extract_jq, 'read', 'process JSON from files in')

    # Strategy E
    registry['git'] = ExtractorEntry(extract_git, 'read', 'access files with git from')

    # Strategy A: create
    for cmd in ('mkdir', 'touch'):
        registry[cmd] = _make_filter_entry('create', f'create {"directories" if cmd == "mkdir" else "or modify files"} in')

    # Strategy A: write (with special validators for mv/cp)
    registry['rm'] = _make_filter_entry('write', 'remove files from')
    registry['rmdir'] = _make_filter_entry('write', 'remove directories from')
    registry['mv'] = _make_filter_entry('write', 'move files to/from', validator=_validate_mv_cp)
    registry['cp'] = _make_filter_entry('write', 'copy files to/from', validator=_validate_mv_cp)

    # Strategy A: read (21 commands)
    _read_commands = {
        'cat': 'concatenate files from',
        'head': 'read the beginning of files from',
        'tail': 'read the end of files from',
        'sort': 'sort contents of files from',
        'uniq': 'filter duplicate lines from files in',
        'wc': 'count lines/words/bytes in files from',
        'cut': 'extract columns from files in',
        'paste': 'merge files from',
        'column': 'format files from',
        'file': 'examine file types in',
        'stat': 'read file stats from',
        'diff': 'compare files from',
        'awk': 'process text from files in',
        'strings': 'extract strings from files in',
        'hexdump': 'display hex dump of files from',
        'od': 'display octal dump of files from',
        'base64': 'encode/decode files from',
        'nl': 'number lines in files from',
        'sha256sum': 'compute SHA-256 checksums for files in',
        'sha1sum': 'compute SHA-1 checksums for files in',
        'md5sum': 'compute MD5 checksums for files in',
    }
    for cmd, desc in _read_commands.items():
        registry[cmd] = _make_filter_entry('read', desc)

    return registry
