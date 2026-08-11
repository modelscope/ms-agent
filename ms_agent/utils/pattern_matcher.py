"""Shared fnmatch pattern matching for hooks and permission modules."""

from __future__ import annotations

import fnmatch


def match_pattern(pattern: str, target: str) -> bool:
    """Match *target* against *pattern* using fnmatch with ``|`` alternatives.

    Examples:
        match_pattern("file_system---*", "file_system---read_file")  -> True
        match_pattern("read_file|write_file", "read_file")           -> True
    """
    for alt in pattern.split('|'):
        alt = alt.strip()
        if alt and fnmatch.fnmatch(target, alt):
            return True
    return False
