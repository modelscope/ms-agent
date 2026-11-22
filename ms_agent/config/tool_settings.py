# Copyright (c) ModelScope Contributors. All rights reserved.
"""Merge tool settings without losing switches or mixing include/exclude lists."""
from copy import deepcopy

from ms_agent.utils.constants import TOOL_PLUGIN_NAME


def merge_tool_settings(base: dict, patch: dict) -> dict:
    """Missing fields inherit; explicit values (including lists) replace.

    ``null`` is not a disable operation. Use ``enabled: false`` so a partial
    config cannot accidentally erase a tool's type or execution settings.
    """
    if not isinstance(base, dict) or not isinstance(patch, dict):
        raise ValueError('tools must be an object; use enabled: false to disable a tool')
    result = deepcopy(base)
    for name, values in patch.items():
        if name == TOOL_PLUGIN_NAME:
            result[name] = deepcopy(values)
            continue
        if not isinstance(values, dict):
            raise ValueError(
                f'tools.{name} must be an object; use enabled: false to disable it')
        for flag in ('enabled', 'mcp'):
            if flag in values and not isinstance(values[flag], bool):
                raise ValueError(f'tools.{name}.{flag} must be a boolean')
        for selector in ('include', 'exclude'):
            if selector in values and (
                    not isinstance(values[selector], list)
                    or any(not isinstance(item, str) for item in values[selector])):
                raise ValueError(f'tools.{name}.{selector} must be a list of names')
        if values.get('include') and values.get('exclude'):
            raise ValueError(f'tools.{name}: set either include or exclude, not both')
        previous = result.get(name) or {}
        if not isinstance(previous, dict):
            raise ValueError(f'tools.{name} must be an object')
        if previous.get('mcp') is False and values.get('mcp') is True:
            raise ValueError(f'tools.{name} is a built-in tool; mcp must be false')
        merged = _merge_mapping(previous, values)
        # Selecting one mode replaces the inherited mode, even for an empty list.
        if 'include' in values and 'exclude' not in values:
            merged.pop('exclude', None)
        if 'exclude' in values and 'include' not in values:
            merged.pop('include', None)
        result[name] = merged
    return result


def _merge_mapping(base: dict, patch: dict) -> dict:
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_mapping(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
