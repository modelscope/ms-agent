# Copyright (c) ModelScope Contributors. All rights reserved.
"""Shared, mutable TUI state.

A tiny value object the renderer writes (token usage, busy flag) and the input
bar reads (to draw the persistent bottom status line). Keeping it in one place
avoids threading half a dozen fields through both components.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TuiState:
    model: str = ''
    perm: str = ''
    work_dir: str = ''
    session_name: str = ''
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    busy: bool = False

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens
