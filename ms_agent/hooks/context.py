"""Hook attachment types and message integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from ms_agent.hooks.events import HookResult
from ms_agent.llm.utils import Message


@dataclass(frozen=True)
class HookAttachment:
    type: Literal[
        'hook_additional_context',
        'hook_blocking_feedback',
        'hook_stopped_continuation',
    ]
    hook_event: str
    tool_call_id: str | None
    content: Union[str, list[str]]


def _append_hook_attachment(
    messages: list[Message],
    attachment: HookAttachment,
) -> None:
    if not messages:
        return
    last = messages[-1]
    if not hasattr(last, 'hook_attachments') or last.hook_attachments is None:
        last.hook_attachments = []
    last.hook_attachments.append(attachment)


def append_stop_blocking_feedback(
    messages: list[Message],
    reason: str,
) -> None:
    """Attach Stop hook block feedback to the assistant turn (§8.5 / §9.4)."""
    if not messages:
        return
    assistant = messages[-1]
    attachment = HookAttachment(
        type='hook_blocking_feedback',
        hook_event='Stop',
        tool_call_id=None,
        content=reason or '',
    )
    if not hasattr(assistant, 'hook_attachments') or assistant.hook_attachments is None:
        assistant.hook_attachments = []
    assistant.hook_attachments.append(attachment)


def apply_hook_result_to_messages(
    messages: list[Message],
    result: HookResult,
    *,
    hook_event: str,
    tool_call_id: str | None = None,
) -> bool:
    """Return False when caller should abort (UserPromptSubmit deny)."""
    if result.action in ('deny', 'block') and hook_event == 'UserPromptSubmit':
        return False
    if result.additional_context:
        _append_hook_attachment(
            messages,
            HookAttachment(
                type='hook_additional_context',
                hook_event=hook_event,
                tool_call_id=tool_call_id,
                content=result.additional_context,
            ),
        )
    return True


def _attachment_to_meta_message(att: HookAttachment) -> Message:
    content = att.content if isinstance(att.content, str) else '\n'.join(
        att.content)
    if att.type == 'hook_blocking_feedback':
        return Message(role='user', content=f'Stop hook feedback:\n{content}')
    if att.type == 'hook_stopped_continuation':
        return Message(role='user', content=f'[hook:{att.hook_event}]\n{content}')
    prefix = f'[hook:{att.hook_event}]'
    return Message(role='user', content=f'{prefix}\n{content}')


def condense_hook_attachments_for_llm(messages: list[Message]) -> list[Message]:
    """Convert hook_attachments into meta user messages for the LLM."""
    out: list[Message] = []
    for msg in messages:
        out.append(msg)
        attachments = getattr(msg, 'hook_attachments', None) or []
        for att in attachments:
            out.append(_attachment_to_meta_message(att))
        if attachments:
            msg.hook_attachments = []
    return out


def extract_latest_user_prompt(messages: list[Message]) -> str:
    for msg in reversed(messages):
        if msg.role == 'user':
            return msg.content if isinstance(msg.content, str) else str(
                msg.content)
    return ''
