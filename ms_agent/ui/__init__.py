# Copyright (c) ModelScope Contributors. All rights reserved.
# isort: skip_file  # noqa
"""UI-agnostic contract layer.

The stable abstraction every front-end depends on (TUI now, WebUI backend and
ACP later). Agent core depends on these protocols, not on any concrete UI —
so the same structured event + async-input contracts validate the WebUI
interface design. Pure stdlib; importing this package pulls in no rich /
prompt_toolkit / omegaconf.
"""
from ms_agent.ui.events import (
    AgentEvent, AgentEventSink, ContentDelta, ContentEnd, ContextCompacted,
    ContextUpdated, ErrorRaised, JsonlEventSink, Notice, PermissionRequested,
    PermissionResolved, PlanEntry, PlanUpdated, QuestionRequested,
    QuestionResolved, ReasoningDelta, ReasoningEnded, ReasoningStarted,
    RecordingSink, TeeEventSink, ToolCallCompleted, ToolCallStarted,
    TurnCompleted, TurnStarted, UsageInfo, UserMessage)
from ms_agent.ui.input import InputSource, StdinInputSource
from ms_agent.ui.interaction import (CUSTOM_OPTION_ID, MAX_HEADER_CHARS,
                                     MAX_OPTIONS, MAX_QUESTIONS, MIN_OPTIONS,
                                     Answer, AnswerStatus, Question,
                                     QuestionHandler, QuestionOption,
                                     QuestionReply, answers_from_dicts)

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
    'QuestionRequested',
    'QuestionResolved',
    'ContextCompacted',
    'ContextUpdated',
    'Notice',
    'ErrorRaised',
    'UsageInfo',
    'RecordingSink',
    'TeeEventSink',
    'JsonlEventSink',
    # input
    'InputSource',
    'StdinInputSource',
    # interaction (model-initiated questions)
    'Answer',
    'AnswerStatus',
    'Question',
    'QuestionHandler',
    'QuestionOption',
    'QuestionReply',
    'answers_from_dicts',
    'CUSTOM_OPTION_ID',
    'MAX_QUESTIONS',
    'MIN_OPTIONS',
    'MAX_OPTIONS',
    'MAX_HEADER_CHARS',
]
