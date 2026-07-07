# Copyright (c) ModelScope Contributors. All rights reserved.
"""Lightweight terminal UI (TUI) for ms-agent.

A route-B REPL (per TUI-PLAN.md): reuses the LLMAgent lifecycle and the
CommandRouter, renders with `rich`, and reads input with `prompt_toolkit`
(graceful fallback to `input()`), so the same SDK that backs the future WebUI
can be exercised end-to-end from a terminal.
"""
from ms_agent.tui.io import RichConsoleIO

__all__ = ['RichConsoleIO']
