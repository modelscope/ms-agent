# Copyright (c) ModelScope Contributors. All rights reserved.
"""Terminal UI (TUI) for ms-agent — a scrolling REPL with a status bar.

A route-A driver over the native LLMAgent lifecycle: the agent owns one
``run_loop`` per session (auto-compaction, single lifecycle, no per-turn
teardown) while the TUI supplies three UI-agnostic seams from ``ms_agent.ui``:

* :class:`~ms_agent.tui.renderer.RichEventSink` — renders the structured
  ``AgentEvent`` stream with ``rich``.
* :class:`~ms_agent.tui.input.PromptToolkitInput` — awaitable input + status bar.
* :class:`~ms_agent.tui.permission.TUIPermissionHandler` — restricted-tool asks.

The same seams a WebUI backend consumes, so the TUI validates that contract.
"""
from ms_agent.tui.app import TuiApp, main
from ms_agent.tui.input import PromptToolkitInput
from ms_agent.tui.renderer import RichEventSink
from ms_agent.tui.state import TuiState

__all__ = ['TuiApp', 'main', 'RichEventSink', 'PromptToolkitInput', 'TuiState']
