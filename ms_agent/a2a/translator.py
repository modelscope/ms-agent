from typing import Any, List

import json
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger

logger = get_logger()


def extract_text_from_a2a_message(message: Any) -> str:
    """Extract concatenated text from an A2A ``Message`` object.

    Handles ``TextPart``, ``FilePart``, and ``DataPart`` within
    ``message.parts``.
    """
    if message is None:
        return ''

    parts = getattr(message, 'parts', None)
    if not parts:
        return str(message) if message else ''

    text_parts: list[str] = []
    for part in parts:
        part_obj = part
        if hasattr(part, 'root'):
            part_obj = part.root

        kind = getattr(part_obj, 'type', None)
        if kind == 'text' or hasattr(part_obj, 'text'):
            text_parts.append(getattr(part_obj, 'text', str(part_obj)))
        elif kind == 'file' or hasattr(part_obj, 'file'):
            file_obj = getattr(part_obj, 'file', None)
            if file_obj:
                name = getattr(file_obj, 'name', 'unnamed')
                mime = getattr(file_obj, 'mimeType', '')
                if hasattr(file_obj, 'bytes'):
                    text_parts.append(
                        f'[File: {name} ({mime}), binary content]')
                elif hasattr(file_obj, 'uri'):
                    text_parts.append(
                        f'[File: {name} ({mime}), uri={file_obj.uri}]')
        elif kind == 'data' or hasattr(part_obj, 'data'):
            data = getattr(part_obj, 'data', part_obj)
            try:
                text_parts.append(json.dumps(data, default=str))
            except (TypeError, ValueError):
                text_parts.append(str(data))
        else:
            text_parts.append(str(part_obj))

    return '\n'.join(text_parts)


def a2a_message_to_ms_messages(
    a2a_message: Any,
    existing_messages: List[Message] | None = None,
) -> List[Message]:
    """Convert an inbound A2A ``Message`` to ms-agent ``Message`` list.

    If ``existing_messages`` is provided, the new user message is appended
    (for multi-turn); otherwise a fresh list is returned.
    """
    user_text = extract_text_from_a2a_message(a2a_message)
    user_msg = Message(role='user', content=user_text)

    if existing_messages is not None:
        existing_messages.append(user_msg)
        return existing_messages
    return [user_msg]


def ms_messages_to_text(messages: List[Message]) -> str:
    """Extract the final assistant response text from ms-agent messages.

    Scans backwards for the last assistant message and returns its text
    content.
    """
    for msg in reversed(messages or []):
        if msg.role == 'assistant':
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        parts.append(block.get('text', str(block)))
                    else:
                        parts.append(str(block))
                text = '\n'.join(parts)
                if text.strip():
                    return text
    return ''


def collect_full_response(messages: List[Message]) -> str:
    """Collect all assistant text across the full message history.

    Useful for assembling a complete response from multi-step agent runs
    where the LLM interleaves tool calls with text fragments.
    """
    parts: list[str] = []
    for msg in (messages or []):
        if msg.role == 'assistant':
            content = msg.content
            if isinstance(content, str) and content.strip():
                parts.append(content)
    return '\n\n'.join(parts) if parts else ''
