"""sed expression safety checks.

Detects dangerous sed expressions (write commands, shell execution, etc.)
and determines whether a sed invocation is read-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_PRINT_ONLY_EXPR = re.compile(r'^(\d+(,\d+)?)?p$')


@dataclass(frozen=True)
class SedSafetyResult:
    safe: bool
    reason: str


def _has_dangerous_sub_flags(expression: str) -> bool:
    """Detect w/e flags in sed s-commands, supporting arbitrary delimiters."""
    i = 0
    n = len(expression)
    while i < n:
        if expression[i] != 's' or i + 1 >= n:
            i += 1
            continue
        delim = expression[i + 1]
        if delim == '\\':
            i += 1
            continue
        pos = i + 2
        found = 0
        while pos < n and found < 2:
            if expression[pos] == '\\' and pos + 1 < n:
                pos += 2
                continue
            if expression[pos] == delim:
                found += 1
            pos += 1
        if found < 2:
            break
        while pos < n and expression[pos] not in ';\n':
            if expression[pos] in 'we':
                return True
            pos += 1
        i = pos
    return False


def is_sed_read_only(args: list[str]) -> bool:
    """Check if sed invocation is read-only: ``-n`` flag, print-only expressions, no ``-i``."""
    has_n = False
    has_i = False
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
            if arg in ('-n', '--quiet', '--silent'):
                has_n = True
            if arg in ('-i', '--in-place') or arg.startswith('-i'):
                has_i = True
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

    if has_i:
        return False
    if not has_n:
        return False
    return all(_PRINT_ONLY_EXPR.match(e.strip()) for e in expressions if e)


def check_sed_expression_safety(expression: str) -> SedSafetyResult:
    """Check a sed expression for dangerous patterns."""
    if not expression:
        return SedSafetyResult(safe=True, reason='Empty expression')

    # Non-ASCII characters (homoglyph attacks)
    try:
        expression.encode('ascii')
    except UnicodeEncodeError:
        return SedSafetyResult(safe=False, reason='Non-ASCII characters in sed expression')

    # Newlines (multi-line command injection)
    if '\n' in expression or '\r' in expression:
        return SedSafetyResult(safe=False, reason='Newline in sed expression')

    # Curly braces (block commands — cannot be statically analysed)
    if '{' in expression or '}' in expression:
        return SedSafetyResult(safe=False, reason='Block commands ({}) in sed expression')

    # w/W command — writes to file
    if re.search(r'(?<![\\])w\s', expression) or re.search(r'(?<![\\])W\s', expression):
        return SedSafetyResult(safe=False, reason='Write command (w/W) in sed expression')

    # e/E command — executes shell command
    if re.search(r'(?<![\\])[eE]$', expression) or re.search(r'(?<![\\])[eE]\s', expression):
        return SedSafetyResult(safe=False, reason='Execute command (e/E) in sed expression')

    # s///w or s///e flags in substitution (arbitrary delimiter aware)
    if _has_dangerous_sub_flags(expression):
        return SedSafetyResult(safe=False, reason='Substitution with w/e flag in sed expression')

    # ! negation (increases analysis complexity)
    if '!' in expression:
        return SedSafetyResult(safe=False, reason='Negation (!) in sed expression')

    return SedSafetyResult(safe=True, reason='Expression passed safety checks')
