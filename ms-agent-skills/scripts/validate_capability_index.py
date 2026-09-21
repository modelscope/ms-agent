#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Validate that SKILL.md Capability Index matches the live registry / MCP set.

Exit code 0 on match, 1 on drift. Intended for CI and local pre-commit checks.

Usage::

    python ms-agent-skills/scripts/validate_capability_index.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / 'SKILL.md'

# Tools that appear in the SKILL.md Capability Index tables.
_TOOL_ROW_RE = re.compile(r'^\|\s*`([a-z][a-z0-9_]*)`\s*\|', re.MULTILINE)


def _tools_from_skill_md(text: str) -> set[str]:
    # Only count rows inside the Capability Index section.
    start = text.find('## Capability Index')
    end = text.find('## Quick Decision Guide')
    if start < 0 or end < 0 or end <= start:
        raise SystemExit('SKILL.md missing Capability Index / Quick Decision Guide')
    section = text[start:end]
    return set(_TOOL_ROW_RE.findall(section))


def main() -> int:
    from ms_agent.capabilities import create_registry
    from ms_agent.capabilities.mcp_server import _is_exposed_over_mcp

    skill_tools = _tools_from_skill_md(SKILL_MD.read_text(encoding='utf-8'))
    registry = create_registry()
    registered = {c.name for c in registry.list_all()}
    mcp_exposed = {c.name for c in registry.list_all() if _is_exposed_over_mcp(c)}

    errors: list[str] = []
    only_in_skill = skill_tools - mcp_exposed
    only_in_mcp = mcp_exposed - skill_tools
    if only_in_skill:
        errors.append(f'In SKILL.md index but not MCP-exposed: {sorted(only_in_skill)}')
    if only_in_mcp:
        errors.append(f'MCP-exposed but missing from SKILL.md index: {sorted(only_in_mcp)}')

    # Parent descriptors may be registered but not MCP-exposed — that is OK,
    # but they must not appear in the skill index.
    parents_in_index = skill_tools & (registered - mcp_exposed)
    if parents_in_index:
        errors.append(
            f'Parent-only descriptors listed in SKILL.md index: '
            f'{sorted(parents_in_index)}')

    print(f'SKILL.md index tools : {len(skill_tools)}')
    print(f'Registry registered  : {len(registered)}')
    print(f'MCP exposed          : {len(mcp_exposed)}')

    if errors:
        print('\nDRIFT DETECTED:')
        for e in errors:
            print(f'  - {e}')
        return 1

    print('OK: SKILL.md Capability Index matches MCP-exposed tools.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
