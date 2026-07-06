import uuid
from typing import Any, Dict, List, Optional

import json
from acp import (plan_entry, start_edit_tool_call, start_read_tool_call,
                 start_tool_call, text_block, tool_content, tool_diff_content,
                 update_agent_message_text, update_agent_thought_text,
                 update_plan, update_tool_call)
from acp.schema import AgentPlanUpdate, ToolCallLocation
from ms_agent.llm.utils import Message
from ms_agent.utils.logger import get_logger

logger = get_logger()

_TOOL_KIND_MAP: Dict[str, str] = {
    'code_executor': 'execute',
    'local_code_executor': 'execute',
    'web_search': 'search',
    'arxiv_search': 'search',
    'exa_search': 'search',
    'serpapi_search': 'search',
    'google_search': 'search',
    'filesystem': 'read',
    'file_read': 'read',
    'file_write': 'edit',
    'todo': 'think',
    'evidence_store': 'think',
    'split_task': 'think',
    'browser': 'fetch',
    'web_browser': 'fetch',
    'mcp_client': 'other',
}

_FILE_EDIT_METHODS = frozenset({
    'write_file',
    'replace_file_contents',
    'file_operation',
    'create_file',
    'edit_file',
    'patch_file',
    'insert_lines',
    'delete_lines',
})

_FILE_READ_METHODS = frozenset({
    'read_file',
    'list_files',
    'file_operation',
    'list_directory',
    'read_directory',
})

_EXEC_METHODS = frozenset({
    'execute_code',
    'run_code',
    'execute',
    'run_command',
    'shell',
    'bash',
})


def _parse_tool_args(arguments: str) -> dict:
    """Best-effort parse tool call arguments JSON."""
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _infer_kind_from_args(tool_name: str, args: dict) -> str:
    """Infer ACP tool kind from tool name and parsed arguments."""
    if tool_name in _TOOL_KIND_MAP:
        kind = _TOOL_KIND_MAP[tool_name]
        if tool_name == 'filesystem':
            method = args.get('method', '') or args.get('operation', '')
            if method in _FILE_EDIT_METHODS:
                return 'edit'
            if method in _FILE_READ_METHODS:
                return 'read'
        return kind

    lower = tool_name.lower()
    if any(
            kw in lower
            for kw in ('write', 'edit', 'create', 'patch', 'replace')):
        return 'edit'
    if any(kw in lower for kw in ('read', 'list', 'get', 'show', 'cat')):
        return 'read'
    if any(kw in lower for kw in ('search', 'find', 'grep', 'query')):
        return 'search'
    if any(
            kw in lower
            for kw in ('exec', 'run', 'shell', 'code', 'bash', 'command')):
        return 'execute'
    if any(kw in lower for kw in ('delete', 'remove', 'rm')):
        return 'delete'
    if any(kw in lower for kw in ('move', 'rename', 'mv')):
        return 'move'
    if any(
            kw in lower
            for kw in ('fetch', 'download', 'browse', 'http', 'url')):
        return 'fetch'
    if any(
            kw in lower
            for kw in ('think', 'plan', 'reason', 'todo', 'evidence')):
        return 'think'
    return 'other'


def _build_title(tool_name: str, args: dict, kind: str) -> str:
    """Build a human-readable title for the IDE's tool call UI."""
    path = (
        args.get('path') or args.get('file_path') or args.get('filename')
        or '')
    method = args.get('method') or args.get('operation') or ''

    if kind == 'edit':
        if path:
            return f'Edit {path}'
        return f'{tool_name}: {method}' if method else tool_name

    if kind == 'read':
        if path:
            return f'Read {path}'
        return f'{tool_name}: {method}' if method else tool_name

    if kind == 'execute':
        code = args.get('code', '') or args.get('command', '')
        if code:
            preview = code.strip().split('\n')[0][:80]
            return f'Run: {preview}'
        return f'Execute {tool_name}'

    if kind == 'search':
        query = args.get('query', '') or args.get('search_query', '')
        if query:
            return f'Search: {query[:60]}'
        return f'Search ({tool_name})'

    if kind == 'think':
        return f'Thinking: {tool_name}'

    if kind == 'fetch':
        url = args.get('url', '') or args.get('uri', '')
        if url:
            return f'Fetch: {url[:60]}'
        return f'Fetch ({tool_name})'

    if kind == 'delete':
        if path:
            return f'Delete {path}'
        return f'Delete ({tool_name})'

    return tool_name


def _extract_locations(args: dict) -> list[ToolCallLocation] | None:
    """Extract file locations from tool arguments for IDE follow-along."""
    path = (
        args.get('path') or args.get('file_path') or args.get('filename')
        or '')
    if not path:
        return None
    line = args.get('line') or args.get('line_number')
    return [
        ToolCallLocation(
            path=path,
            line=int(line) if line is not None else None,
        )
    ]


def _extract_file_path(args: dict) -> str:
    """Extract file path from tool arguments."""
    return (args.get('path') or args.get('file_path') or args.get('filename')
            or '')


def _try_parse_diff_from_result(
    tool_name: str,
    args: dict,
    result_text: str,
) -> Optional[dict]:
    """Attempt to extract diff info (path, old_text, new_text) from tool
    arguments and result for file-edit operations.

    Returns a dict with path/old_text/new_text if applicable, else None.
    """
    path = _extract_file_path(args)
    if not path:
        return None

    method = (args.get('method') or args.get('operation', '')).lower()

    if method == 'write' or tool_name == 'file_write':
        new_text = args.get('content', '')
        if new_text:
            return {'path': path, 'old_text': None, 'new_text': new_text}

    if 'write_file' in tool_name or method == 'write_file':
        new_text = args.get('content', '')
        if new_text:
            return {'path': path, 'old_text': None, 'new_text': new_text}

    if 'replace' in tool_name or 'replace' in method:
        source = args.get('source', '') or args.get('old_text', '')
        target = args.get('target', '') or args.get('new_text', '')
        if source and target:
            return {'path': path, 'old_text': source, 'new_text': target}

    return None


class ACPTranslator:
    """Stateful translator: bidirectional mapping between ACP protocol schema
    and ms-agent Message objects.

    Create one instance per session so delta tracking stays session-scoped.
    """

    def __init__(self) -> None:
        self._last_content_len: int = 0
        self._last_reasoning_len: int = 0
        self._emitted_tool_ids: set[str] = set()
        self._completed_tool_ids: set[str] = set()
        self._tool_args_cache: dict[str, dict] = {}
        self._tool_name_cache: dict[str, str] = {}
        self._last_seen_msg_count: int = 0

    def reset_turn(self, prior_msg_count: int = 0) -> None:
        """Reset per-turn delta tracking. Call at the start of each prompt.

        ``prior_msg_count`` is the number of messages that already existed
        before this turn.  Setting it correctly prevents the translator from
        replaying old assistant content as new deltas in multi-turn sessions.
        """
        self._last_content_len = 0
        self._last_reasoning_len = 0
        self._emitted_tool_ids.clear()
        self._completed_tool_ids.clear()
        self._tool_args_cache.clear()
        self._tool_name_cache.clear()
        self._last_seen_msg_count = prior_msg_count

    @staticmethod
    def prompt_to_messages(
        prompt: list,
        existing_messages: List[Message] | None = None,
    ) -> List[Message]:
        """Convert an ACP prompt (list of ContentBlocks) to ms-agent Messages.

        If ``existing_messages`` is provided the new user message is appended;
        otherwise a fresh list is returned.
        """
        parts: list[str] = []
        for block in prompt:
            block_type = getattr(block, 'type', None)
            if block_type == 'text':
                parts.append(block.text)
            elif block_type == 'resource':
                res = block.resource
                if hasattr(res, 'text'):
                    parts.append(
                        f'[Resource: {getattr(res, "uri", "")}]\n{res.text}')
                elif hasattr(res, 'blob'):
                    parts.append(
                        f'[Binary resource: {getattr(res, "uri", "")}]')
            elif block_type == 'resource_link':
                uri = getattr(block, 'uri', '')
                parts.append(f'[Resource link: {uri}]')
            elif block_type == 'image':
                parts.append('[Image content attached]')
            else:
                parts.append(str(block))

        user_text = '\n'.join(parts)
        user_msg = Message(role='user', content=user_text)

        if existing_messages is not None:
            existing_messages.append(user_msg)
            return existing_messages
        return [user_msg]

    def messages_to_updates(
        self,
        messages: List[Message],
    ) -> list:
        """Diff the current message list against what was already sent
        and return a list of ACP SessionUpdate objects for the new content.

        Processes ALL new messages since the last call, not just the last one.
        This ensures tool results from parallel_tool_call are not missed.
        """
        updates: list = []
        if not messages:
            return updates

        start = max(self._last_seen_msg_count, 0)
        new_messages = messages[start:]
        self._last_seen_msg_count = len(messages)

        if not new_messages:
            last_msg = messages[-1]
            if last_msg.role == 'assistant':
                updates.extend(self._translate_assistant(last_msg))
            return updates

        for msg in new_messages:
            if msg.role == 'assistant':
                updates.extend(self._translate_assistant(msg))
            elif msg.role == 'tool':
                updates.extend(self._translate_tool_result(msg))

        return updates

    def _translate_assistant(self, msg: Message) -> list:
        updates: list = []
        content = msg.content if isinstance(msg.content, str) else ''
        reasoning = msg.reasoning_content or ''

        if reasoning and len(reasoning) > self._last_reasoning_len:
            delta = reasoning[self._last_reasoning_len:]
            self._last_reasoning_len = len(reasoning)
            updates.append(update_agent_thought_text(delta))

        if content and len(content) > self._last_content_len:
            delta = content[self._last_content_len:]
            self._last_content_len = len(content)
            updates.append(update_agent_message_text(delta))

        for tc in (msg.tool_calls or []):
            tc_id = tc.get('id', '') or f'tc_{uuid.uuid4().hex[:8]}'
            if tc_id in self._emitted_tool_ids:
                continue
            self._emitted_tool_ids.add(tc_id)

            tool_name = tc.get('tool_name', 'unknown')
            raw_args = tc.get('arguments', '')
            args = _parse_tool_args(raw_args)
            self._tool_args_cache[tc_id] = args
            self._tool_name_cache[tc_id] = tool_name

            kind = _infer_kind_from_args(tool_name, args)
            title = _build_title(tool_name, args, kind)
            locations = _extract_locations(args)
            path = _extract_file_path(args)

            if kind == 'edit' and path:
                content_preview = args.get('content', '')
                updates.append(
                    start_edit_tool_call(
                        tool_call_id=tc_id,
                        title=title,
                        path=path,
                        content=content_preview,
                    ))
            elif kind == 'read' and path:
                updates.append(
                    start_read_tool_call(
                        tool_call_id=tc_id,
                        title=title,
                        path=path,
                    ))
            else:
                updates.append(
                    start_tool_call(
                        tool_call_id=tc_id,
                        title=title,
                        kind=kind,
                        status='in_progress',
                        locations=locations,
                        raw_input=raw_args if raw_args else None,
                    ))

        return updates

    def _translate_tool_result(self, msg: Message) -> list:
        updates: list = []
        tc_id = msg.tool_call_id or ''
        if not tc_id or tc_id in self._completed_tool_ids:
            return updates
        self._completed_tool_ids.add(tc_id)

        result_text = (
            msg.content if isinstance(msg.content, str) else str(msg.content))
        tool_name = self._tool_name_cache.get(tc_id, msg.name or '')
        args = self._tool_args_cache.get(tc_id, {})
        kind = _infer_kind_from_args(tool_name, args)
        is_error = self._looks_like_error(result_text)

        content_items: list = []

        if kind == 'edit' and not is_error:
            diff = _try_parse_diff_from_result(tool_name, args, result_text)
            if diff:
                content_items.append(
                    tool_diff_content(
                        path=diff['path'],
                        new_text=diff['new_text'],
                        old_text=diff.get('old_text'),
                    ))
            if result_text:
                content_items.append(tool_content(text_block(result_text)))
        elif result_text:
            content_items.append(tool_content(text_block(result_text)))

        status = 'failed' if is_error else 'completed'

        updates.append(
            update_tool_call(
                tool_call_id=tc_id,
                status=status,
                content=content_items if content_items else None,
                raw_output=result_text or None,
            ))
        return updates

    @staticmethod
    def _looks_like_error(text: str) -> bool:
        if not text:
            return False
        lower = text.lower()[:200]
        error_markers = ('error:', 'failed', 'exception', 'traceback',
                         '"success": false', "'success': false")
        return any(m in lower for m in error_markers)

    @staticmethod
    def build_plan_update(steps: list[dict]) -> AgentPlanUpdate:
        """Build an ACP plan update from a list of research steps.

        Each step dict should have ``description``, ``status`` (pending /
        in_progress / completed), and optionally ``priority``.
        """
        entries = [
            plan_entry(
                content=s.get('description', ''),
                status=s.get('status', 'pending'),
                priority=s.get('priority', 'medium'),
            ) for s in steps
        ]
        return update_plan(entries)

    @staticmethod
    def map_stop_reason(
        session,
        cancelled: bool = False,
    ) -> str:
        """Map ms-agent runtime state to an ACP stop reason literal."""
        if cancelled or (hasattr(session, 'cancelled') and session.cancelled):
            return 'cancelled'

        agent = session.agent
        rt = getattr(agent, 'runtime', None)
        if rt is None:
            return 'end_turn'

        max_rounds = getattr(agent, 'max_chat_round',
                             getattr(agent, 'DEFAULT_MAX_CHAT_ROUND', 20))
        if rt.round >= max_rounds + 1:
            return 'max_turn_requests'

        return 'end_turn'
