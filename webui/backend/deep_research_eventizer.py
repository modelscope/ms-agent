from typing import Any, Callable, Dict, List, Optional

import json
from ms_agent.llm.utils import Message, ToolCall


def _stringify_content(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


class HistoryEventizer:

    def __init__(
        self,
        emit: Callable[[Dict[str, Any]], None],
        *,
        channel: str = 'main',
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        card_id: Optional[str] = None,
    ) -> None:
        self._emit = emit
        self._channel = channel
        self._session_id = session_id
        self._turn_id = turn_id
        self._card_id = card_id
        self._prev_messages: List[Message] = []
        self._message_ids: List[str] = []
        self._assistant_contents: Dict[str, str] = {}
        self._completed_messages: set[str] = set()
        self._seen_tool_calls: set[str] = set()
        self._seen_tool_results: set[str] = set()
        self._subagent_call_ids: set[str] = set()
        self._tool_call_args: Dict[str, Dict[str, Any]] = {}
        self._tool_call_names: Dict[str, str] = {}

    def reset(self) -> None:
        self._prev_messages = []
        self._message_ids = []
        self._assistant_contents = {}
        self._completed_messages = set()
        self._seen_tool_calls = set()
        self._seen_tool_results = set()
        self._subagent_call_ids = set()
        self._tool_call_args = {}
        self._tool_call_names = {}

    def _wrap_event(self, event_type: str,
                    payload: Dict[str, Any]) -> Dict[str, Any]:
        event: Dict[str, Any] = {'type': event_type, 'payload': payload}
        if self._session_id:
            event['session_id'] = self._session_id
        if self._turn_id:
            event['turn_id'] = self._turn_id
        return event

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        self._emit(self._wrap_event(event_type, payload))

    def _should_reset(self, messages: List[Message]) -> bool:
        if len(messages) < len(self._prev_messages):
            return True
        for idx, msg in enumerate(messages[:len(self._prev_messages)]):
            if msg.role != self._prev_messages[idx].role:
                return True
        return False

    def _ensure_message_id(self, idx: int, message: Message) -> str:
        if idx < len(self._message_ids):
            return self._message_ids[idx]
        raw_id = getattr(message, 'id', None)
        if raw_id:
            msg_id = raw_id
        else:
            prefix = self._card_id or self._channel
            msg_id = f'{prefix}-{idx}'
        self._message_ids.append(msg_id)
        return msg_id

    def _is_subagent_tool(self, tool_name: str) -> bool:
        if not tool_name:
            return False
        return tool_name.startswith('agent_tools---') or tool_name.endswith(
            'searcher_tool') or tool_name.endswith('reporter_tool')

    def _extract_tool_name(self, call: ToolCall) -> str:
        if not isinstance(call, dict):
            return ''
        tool_name = call.get('tool_name')
        if tool_name:
            return tool_name
        func = call.get('function') or {}
        if isinstance(func, dict):
            return func.get('name', '') or ''
        return ''

    def _extract_tool_args_raw(self, call: ToolCall) -> Any:
        if not isinstance(call, dict):
            return {}
        if 'arguments' in call:
            return call.get('arguments')
        func = call.get('function') or {}
        if isinstance(func, dict):
            return func.get('arguments', {})
        return {}

    def _parse_tool_args(self, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return {'request': raw}
        if isinstance(raw, list):
            return {'messages': raw}
        if raw is not None:
            return {'request': raw}
        return {}

    def _build_subagent_title(self, tool_name: str,
                              tool_args: Dict[str, Any]) -> str:
        if 'searcher' in tool_name:
            base = 'Searcher'
        elif 'reporter' in tool_name:
            base = 'Reporter'
        else:
            base = tool_name.split('---')[-1] or tool_name

        request = tool_args.get('request')
        summary = None
        if isinstance(request, str) and request.strip():
            try:
                parsed = json.loads(request)
                if isinstance(parsed, dict):
                    summary = parsed.get('task_id') or parsed.get(
                        '调研目标') or parsed.get('目标')
            except Exception:
                summary = None
            if summary is None:
                summary = request.strip().splitlines()[0][:80]
        return f'{base}: {summary}' if summary else base

    def _record_tool_call(self, call_id: str, tool_name: str,
                          tool_args: Dict[str, Any]) -> tuple[bool, bool]:
        is_new = call_id not in self._seen_tool_calls
        prev_args = self._tool_call_args.get(call_id)
        prev_name = self._tool_call_names.get(call_id)
        if (not is_new and prev_args == tool_args
                and (not tool_name or tool_name == prev_name)):
            return False, False
        self._seen_tool_calls.add(call_id)
        self._tool_call_args[call_id] = tool_args
        if tool_name:
            self._tool_call_names[call_id] = tool_name
        return True, is_new

    def _maybe_emit_todos(self, tool_name: str, result_text: str,
                          call_id: Optional[str]) -> None:
        if not tool_name:
            return
        if not ('todo_list---todo_write' in tool_name
                or 'todo_list---todo_read' in tool_name):
            return
        try:
            parsed = json.loads(result_text)
        except Exception:
            return
        todos = None
        if isinstance(parsed, dict):
            todos = parsed.get('todos')
        elif isinstance(parsed, list):
            todos = parsed
        if isinstance(todos, list):
            payload: Dict[str, Any] = {'todos': todos}
            if call_id:
                payload['call_id'] = call_id
            self._emit_event('dr.state', payload)

    def _emit_assistant_delta(self, message_id: str, delta: str,
                              full: str) -> None:
        payload = {
            'message_id': message_id,
            'delta': delta,
            'full': full,
        }
        self._emit_event('dr.chat.message.delta', payload)

    def _emit_subagent_delta(self, message_id: str, delta: str,
                             full: str) -> None:
        payload = {
            'card_id': self._card_id,
            'message_id': message_id,
            'delta': delta,
            'full': full,
        }
        self._emit_event('dr.subagent.message.delta', payload)

    def _emit_subagent_message(self, message_id: str, role: str,
                               content: str) -> None:
        payload = {
            'card_id': self._card_id,
            'message_id': message_id,
            'role': role,
            'content': content,
        }
        self._emit_event('dr.subagent.message', payload)

    def _emit_assistant_completed(self, message_id: str, content: str) -> None:
        payload = {
            'message_id': message_id,
            'role': 'assistant',
            'content': content,
        }
        self._emit_event('dr.chat.message.completed', payload)

    def _emit_chat_message(self, message_id: str, role: str, content: str,
                           name: Optional[str]) -> None:
        payload = {
            'message_id': message_id,
            'role': role,
            'content': content,
        }
        if name:
            payload['name'] = name
        self._emit_event('dr.chat.message', payload)

    def _process_tool_calls(self, message_id: str,
                            tool_calls: List[ToolCall]) -> None:
        for idx, call in enumerate(tool_calls or []):
            call_id = call.get('id') or f'{message_id}-call-{idx}'
            tool_name = self._extract_tool_name(call)
            tool_args = self._parse_tool_args(
                self._extract_tool_args_raw(call))
            should_emit, is_new = self._record_tool_call(
                call_id, tool_name, tool_args)
            if not should_emit:
                continue
            category = 'subagent' if self._is_subagent_tool(
                tool_name) else 'normal'
            payload = {
                'call_id': call_id,
                'source_message_id': message_id,
                'tool': {
                    'name': tool_name,
                    'arguments': tool_args,
                },
                'category': category,
            }
            if not is_new:
                payload['updated'] = True
            self._emit_event('dr.tool.call', payload)
            if category == 'subagent' and call_id not in self._subagent_call_ids:
                self._subagent_call_ids.add(call_id)
                card_payload = {
                    'card_id': call_id,
                    'tool_name': tool_name,
                    'title': self._build_subagent_title(tool_name, tool_args),
                    'source_message_id': message_id,
                }
                self._emit_event('dr.subagent.card.start', card_payload)

    def _process_tool_result(self, message: Message) -> None:
        call_id = message.tool_call_id
        if not call_id or call_id in self._seen_tool_results:
            return
        self._seen_tool_results.add(call_id)
        tool_name = message.name or ''
        result_text = _stringify_content(message.content)
        payload: Dict[str, Any] = {
            'call_id': call_id,
            'tool_name': tool_name,
            'result_text': result_text,
            'is_error': False,
        }
        tool_args = self._tool_call_args.get(call_id)
        if tool_args is not None:
            payload['tool'] = {
                'name': tool_name or self._tool_call_names.get(call_id, ''),
                'arguments': tool_args,
            }
        self._emit_event('dr.tool.result', payload)
        if call_id in self._subagent_call_ids:
            summary = result_text.strip().splitlines()[0][:160]
            self._emit_event('dr.subagent.card.completed', {
                'card_id': call_id,
                'summary': summary,
            })
        self._maybe_emit_todos(tool_name, result_text, call_id)

    def process(self, messages: List[Message]) -> None:
        if not messages:
            return
        if self._should_reset(messages):
            self.reset()

        prev_len = len(self._prev_messages)
        for idx, message in enumerate(messages):
            message_id = self._ensure_message_id(idx, message)
            role = message.role

            if self._channel == 'main':
                if role == 'assistant':
                    content = _stringify_content(message.content)
                    prev_content = self._assistant_contents.get(message_id, '')
                    if content and content != prev_content:
                        if content.startswith(prev_content):
                            delta = content[len(prev_content):]
                        else:
                            delta = content
                        if delta:
                            self._emit_assistant_delta(message_id, delta,
                                                       content)
                        self._assistant_contents[message_id] = content
                    if message.tool_calls:
                        self._process_tool_calls(message_id,
                                                 message.tool_calls)
                elif role == 'tool':
                    self._process_tool_result(message)
                else:
                    if role == 'system':
                        continue
                    if idx >= prev_len:
                        content = _stringify_content(message.content)
                        if content:
                            self._emit_chat_message(
                                message_id, role, content,
                                getattr(message, 'name', None))
            else:
                if role == 'assistant':
                    content = _stringify_content(message.content)
                    prev_content = self._assistant_contents.get(message_id, '')
                    if content and content != prev_content:
                        if content.startswith(prev_content):
                            delta = content[len(prev_content):]
                        else:
                            delta = content
                        if delta:
                            self._emit_subagent_delta(message_id, delta,
                                                      content)
                        self._assistant_contents[message_id] = content
                    if message.tool_calls:
                        for idx, call in enumerate(message.tool_calls or []):
                            call_id = call.get(
                                'id') or f'{message_id}-call-{idx}'
                            tool_name = self._extract_tool_name(call)
                            tool_args = self._parse_tool_args(
                                self._extract_tool_args_raw(call))
                            should_emit, is_new = self._record_tool_call(
                                call_id, tool_name, tool_args)
                            if not should_emit:
                                continue
                            payload = {
                                'card_id': self._card_id,
                                'call_id': call_id,
                                'source_message_id': message_id,
                                'tool': {
                                    'name': tool_name,
                                    'arguments': tool_args,
                                },
                            }
                            if not is_new:
                                payload['updated'] = True
                            self._emit_event('dr.subagent.tool.call', payload)
                else:
                    if role == 'system':
                        continue
                    if role != 'tool' and idx >= prev_len:
                        content = _stringify_content(message.content)
                        if content:
                            self._emit_subagent_message(
                                message_id, role, content)
                    if role == 'tool' and message.tool_call_id:
                        call_id = message.tool_call_id
                        if call_id in self._seen_tool_results:
                            continue
                        self._seen_tool_results.add(call_id)
                        tool_name = message.name or ''
                        payload: Dict[str, Any] = {
                            'card_id': self._card_id,
                            'call_id': call_id,
                            'tool_name': tool_name,
                            'result_text': _stringify_content(message.content),
                        }
                        tool_args = self._tool_call_args.get(call_id)
                        if tool_args is not None:
                            payload['tool'] = {
                                'name':
                                (tool_name
                                 or self._tool_call_names.get(call_id, '')),
                                'arguments':
                                tool_args,
                            }
                        self._emit_event('dr.subagent.tool.result', payload)

        if self._channel == 'main':
            last_idx = len(messages) - 1
            for idx, message in enumerate(messages):
                if message.role != 'assistant':
                    continue
                if idx >= last_idx:
                    continue
                msg_id = self._message_ids[idx]
                if msg_id in self._completed_messages:
                    continue
                content = self._assistant_contents.get(msg_id, '')
                self._emit_assistant_completed(msg_id, content)
                self._completed_messages.add(msg_id)

        self._prev_messages = list(messages)

    def finalize(self) -> None:
        if self._channel != 'main':
            return
        if not self._prev_messages:
            return
        last_idx = len(self._prev_messages) - 1
        last_msg = self._prev_messages[last_idx]
        if last_msg.role != 'assistant':
            return
        msg_id = self._message_ids[last_idx]
        if msg_id in self._completed_messages:
            return
        content = self._assistant_contents.get(msg_id, '')
        self._emit_assistant_completed(msg_id, content)
        self._completed_messages.add(msg_id)
