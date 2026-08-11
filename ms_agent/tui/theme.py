# Copyright (c) ModelScope Contributors. All rights reserved.
"""Centralized TUI styling — one place to tune colors, so nothing is hardcoded
across the renderer / input / permission modules. Values are ``rich`` style
strings; keep them theme-neutral (readable on both light and dark terminals).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    user: str = 'bold cyan'
    assistant: str = 'bold green'
    assistant_label: str = 'green'
    reasoning: str = 'dim'
    tool_bullet: str = 'cyan'
    tool_border: str = 'yellow'
    tool_name: str = 'bold yellow'
    tool_result_border: str = 'green'
    tool_error_border: str = 'red'
    error_border: str = 'red'
    notice_info: str = 'dim'
    notice_success: str = 'green'
    notice_warning: str = 'yellow'
    permission_border: str = 'magenta'
    banner_border: str = 'cyan'
    banner_label: str = 'bold cyan'
    rule: str = 'cyan'
    session_marker: str = 'bold green'
    status_bar: str = 'dim'
    prompt: str = 'bold cyan'
    hint: str = 'dim'

    # symbols (kept here so the visual language is consistent + swappable)
    prompt_symbol: str = '❯'
    user_symbol: str = '❯'
    assistant_symbol: str = '●'
    tool_symbol: str = '▸'
    result_symbol: str = '←'


DEFAULT_THEME = Theme()
