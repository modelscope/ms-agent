"""Safe wrapper stripping: remove harmless command wrappers so the real
command can be analysed for path extraction.

Two-phase algorithm:
  Phase 1 — strip safe environment variable assignments (VAR=val).
  Phase 2 — strip wrapper commands (timeout, time, nice, nohup, stdbuf, env).
"""

from __future__ import annotations

import re

# Environment variables safe to strip (do not affect paths or inject code).
SAFE_ENV_VARS: frozenset[str] = frozenset({
    # Go
    'GOEXPERIMENT', 'GOOS', 'GOARCH', 'CGO_ENABLED', 'GO111MODULE',
    # Rust
    'RUST_BACKTRACE', 'RUST_LOG',
    # Node
    'NODE_ENV',
    # Python
    'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE',
    # Pytest
    'PYTEST_DISABLE_PLUGIN_AUTOLOAD', 'PYTEST_DEBUG',
    # Locale / encoding
    'LANG', 'LANGUAGE', 'LC_ALL', 'LC_CTYPE', 'LC_TIME', 'CHARSET',
    # Terminal / display
    'TERM', 'COLORTERM', 'NO_COLOR', 'FORCE_COLOR', 'TZ',
    # Color config
    'LS_COLORS', 'LSCOLORS', 'GREP_COLOR', 'GREP_COLORS', 'GCC_COLORS',
    # Display format
    'TIME_STYLE', 'BLOCK_SIZE', 'BLOCKSIZE',
})

_SAFE_FLAG_VALUE = re.compile(r'^[A-Za-z0-9_.+\-]+$')
_ENV_ASSIGN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)=')


def _strip_env_vars(tokens: list[str]) -> list[str]:
    """Phase 1: strip leading safe environment variable assignments."""
    i = 0
    while i < len(tokens):
        m = _ENV_ASSIGN.match(tokens[i])
        if not m:
            break
        var_name = m.group(1)
        if var_name not in SAFE_ENV_VARS:
            break
        i += 1
    return tokens[i:]


def _strip_timeout(tokens: list[str]) -> list[str] | None:
    """Strip ``timeout`` wrapper with its flags and duration argument."""
    if not tokens or tokens[0] != 'timeout':
        return None

    no_value_flags = frozenset({'--foreground', '--preserve-status', '-v', '--verbose'})
    value_flags_long = frozenset({'--kill-after', '--signal'})
    value_flags_short = frozenset({'-k', '-s'})

    i = 1
    while i < len(tokens):
        arg = tokens[i]
        if arg == '--':
            i += 1
            break
        if arg in no_value_flags:
            i += 1
            continue
        if arg in value_flags_long:
            i += 2  # flag + value
            continue
        if any(arg.startswith(f'{f}=') for f in value_flags_long):
            i += 1
            continue
        for short in value_flags_short:
            if arg == short:
                i += 2
                break
            if arg.startswith(short) and len(arg) > len(short):
                val = arg[len(short):]
                if not _SAFE_FLAG_VALUE.match(val):
                    return None  # suspicious flag value
                i += 1
                break
        else:
            if arg.startswith('-'):
                i += 1
                continue
            # This is the duration argument
            i += 1
            break
    return tokens[i:]


def _strip_time(tokens: list[str]) -> list[str] | None:
    if not tokens or tokens[0] != 'time':
        return None
    i = 1
    while i < len(tokens) and tokens[i].startswith('-'):
        i += 1
    return tokens[i:]


def _strip_nice(tokens: list[str]) -> list[str] | None:
    """Strip ``nice`` in three forms: bare, ``-N``, ``-n N``."""
    if not tokens or tokens[0] != 'nice':
        return None
    i = 1
    if i < len(tokens):
        if tokens[i] in ('-n', '--adjustment'):
            i += 2  # -n N
        elif tokens[i].startswith('-') and tokens[i][1:].lstrip('-').isdigit():
            i += 1  # -N (traditional)
    return tokens[i:]


def _strip_nohup(tokens: list[str]) -> list[str] | None:
    if not tokens or tokens[0] != 'nohup':
        return None
    return tokens[1:]


def _strip_stdbuf(tokens: list[str]) -> list[str] | None:
    if not tokens or tokens[0] != 'stdbuf':
        return None
    # stdbuf flags: -i MODE, -o MODE, -e MODE (or combined: -iL, -o0, --input=MODE)
    i = 1
    while i < len(tokens):
        arg = tokens[i]
        if arg == '--':
            i += 1
            break
        if arg.startswith('-'):
            if '=' in arg or len(arg) > 2:
                i += 1  # combined flag+value (e.g. -o0, --input=L)
            else:
                i += 2  # separate value (e.g. -o 0)
            continue
        break
    return tokens[i:]


def _strip_env(tokens: list[str]) -> list[str] | None:
    """Strip ``env`` wrapper with safe flags."""
    if not tokens or tokens[0] != 'env':
        return None

    unsafe_flags = frozenset({'-S', '--split-string', '-C', '--chdir', '-P', '--path'})
    safe_no_value = frozenset({'-i', '--ignore-environment', '-0', '--null', '-v', '--verbose'})

    i = 1
    while i < len(tokens):
        arg = tokens[i]
        if arg in unsafe_flags:
            return None  # cannot safely strip
        if arg in safe_no_value:
            i += 1
            continue
        if arg in ('-u', '--unset'):
            i += 2
            continue
        if arg == '--':
            i += 1
            break
        if _ENV_ASSIGN.match(arg):
            i += 1
            continue
        if arg.startswith('-'):
            return None  # unknown flag
        break
    return tokens[i:]


_WRAPPER_STRIPPERS = [
    _strip_timeout,
    _strip_time,
    _strip_nice,
    _strip_nohup,
    _strip_stdbuf,
    _strip_env,
]


def strip_safe_wrappers(tokens: list[str]) -> list[str]:
    """Strip safe wrappers from a tokenized command.

    Phase 1: strip leading safe env var assignments.
    Phase 2: iteratively strip wrapper commands.
    """
    if not tokens:
        return tokens

    # Phase 1: environment variables
    tokens = _strip_env_vars(tokens)
    if not tokens:
        return tokens

    # Phase 2: wrapper commands (iterate until stable)
    changed = True
    while changed and tokens:
        changed = False
        for stripper in _WRAPPER_STRIPPERS:
            result = stripper(tokens)
            if result is not None:
                tokens = result
                changed = True
                break
    return tokens
