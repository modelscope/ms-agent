"""Hooks system — shell-based lifecycle hooks with multi-platform config support."""

from ms_agent.hooks.bridge import CallbackToHookBridge
from ms_agent.hooks.context import (
    HookAttachment,
    apply_hook_result_to_messages,
    append_stop_blocking_feedback,
    condense_hook_attachments_for_llm,
    extract_latest_user_prompt,
)
from ms_agent.hooks.events import HookResult
from ms_agent.hooks.factory import build_hook_runtime
from ms_agent.hooks.registry import HookHandlerConfig, HookRegistry, MatcherGroup
from ms_agent.hooks.runtime import HookRuntime

__all__ = [
    'CallbackToHookBridge',
    'HookAttachment',
    'HookHandlerConfig',
    'HookRegistry',
    'HookResult',
    'HookRuntime',
    'MatcherGroup',
    'apply_hook_result_to_messages',
    'append_stop_blocking_feedback',
    'build_hook_runtime',
    'condense_hook_attachments_for_llm',
    'extract_latest_user_prompt',
]
