# Copyright (c) ModelScope Contributors. All rights reserved.
"""UI-agnostic contract layer.

The stable abstraction every front-end depends on (TUI now, WebUI backend and
ACP later). Agent core depends on these protocols, not on any concrete UI —
so the same structured event + async-input contracts validate the WebUI
interface design. Pure stdlib; importing this package pulls in no rich /
prompt_toolkit / omegaconf.
"""
from ms_agent.ui.events import (
    AgentEvent,
    AgentEventSink,
    ContentDelta,
    ContentEnd,
    ContextCompacted,
    ErrorRaised,
    Notice,
    PermissionRequested,
    PermissionResolved,
    PlanEntry,
    PlanUpdated,
    ReasoningDelta,
    ReasoningEnded,
    ReasoningStarted,
    RecordingSink,
    JsonlEventSink,
    TeeEventSink,
    ToolCallCompleted,
    ToolCallStarted,
    TurnCompleted,
    TurnStarted,
    UsageInfo,
    UserMessage,
)
from ms_agent.ui.input import InputSource, StdinInputSource

__all__ = [
    # events
    'AgentEvent',
    'AgentEventSink',
    'TurnStarted',
    'UserMessage',
    'TurnCompleted',
    'ContentDelta',
    'ContentEnd',
    'ReasoningStarted',
    'ReasoningDelta',
    'ReasoningEnded',
    'ToolCallStarted',
    'ToolCallCompleted',
    'PlanEntry',
    'PlanUpdated',
    'PermissionRequested',
    'PermissionResolved',
    'ContextCompacted',
    'Notice',
    'ErrorRaised',
    'UsageInfo',
    'RecordingSink',
    'TeeEventSink',
    'JsonlEventSink',
    # input
    'InputSource',
    'StdinInputSource',
]
