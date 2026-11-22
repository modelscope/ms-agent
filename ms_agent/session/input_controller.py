# Copyright (c) ModelScope Contributors. All rights reserved.
"""Durable, single-event-loop admission and scheduling of session inputs.

An accepted input is *not* a conversation message. Only a canonical user row
commits delivery. All mutations below are synchronous (including the journal
write), so admission, dispatch and the final-turn check have no await window.
The host owns execution tasks; this module owns ordering and recovery.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Callable
from uuid import uuid4


class InputConflict(ValueError):
    """A stale target, revision or reused submission identity."""


def skipped_tool_result(call):
    """Only valid BEFORE dispatch. This is a runtime fact, not an observation."""
    import json

    from ms_agent.llm.utils import Message, ToolResult
    result = ToolResult(
        text=json.dumps({
            'source':
            'agent_runtime',
            'status':
            'not_executed',
            'reason':
            'superseded_by_user_input',
            'result':
            None,
            'message':
            'This tool call was not executed. No tool output is available. '
            'Consider the following user messages before deciding '
            'whether a new tool call is needed.',
        }),
        is_error=True)
    message = Message(
        role='tool',
        content=result.text,
        is_error=True,
        tool_call_id=call['id'],
        name=call.get('tool_name') or call.get('name') or '')
    message.execution_status = 'skipped'
    message.skip_reason = 'superseded_by_user_input'
    return message


class SessionInputController:
    MAX_PENDING = 20

    def __init__(self, log, on_change: Callable | None = None, workspace=None):
        self.log = log
        self.on_change = on_change
        self.workspace = workspace
        self.inputs: dict[str, dict] = {}
        self.active_turn: str | None = None
        self.active_input: str | None = None
        self.segment_id: str | None = None
        self.stopping = False
        self._hold_generation = 0
        self._preparing: dict[str, tuple[dict, asyncio.Task]] = {}
        open_task = None
        for row in log.records():
            if row.get('_type') == 'input_event':
                if row.get('input'):
                    self.inputs[row['input']['input_id']] = row['input']
                if row.get('task'):
                    open_task = row['task'] if row['task'][
                        'state'] == 'started' else None
            elif row.get('role') == 'user' and row.get(
                    'input_id') in self.inputs:
                self.inputs[row['input_id']].update(
                    state='delivered',
                    turn_id=row.get('turn_id'),
                    message_id=row.get('message_id'))
        # Process restart never replays accepted work without an explicit act.
        # A delivered input is never replayed, even if its task did not finish.
        for item in self.inputs.values():
            if item['state'] == 'pending':
                item.pop('claimed', None)
                item['held'] = item.get('held') or 'restart'
                self._record(item)
        self._seal_restarted_task(open_task)

    def _seal_restarted_task(self, open_task):
        rows = self.log.get_visible_messages()
        if not self.inputs or not rows or (open_task and not any(
                row.get('turn_id') == open_task['turn_id'] for row in rows)):
            if open_task:
                self._task_event('interrupted', open_task['turn_id'])
            return
        last = rows[-1]
        if last.get('role') == 'assistant' and not last.get('tool_calls') and (
                not open_task or last.get('interrupted')):
            if open_task:
                self._task_event('interrupted', open_task['turn_id'])
            return
        # The process may have died AFTER a side effect but BEFORE its result
        # reached the log. Never label that outcome "not executed" or replay it.
        results = {
            row.get('tool_call_id')
            for row in rows if row.get('role') == 'tool'
        }
        for row in rows:
            for call in row.get('tool_calls') or []:
                if call.get('id') not in results:
                    self.log.append({
                        'role':
                        'tool',
                        'tool_call_id':
                        call['id'],
                        'name':
                        call.get('tool_name') or call.get('name') or '',
                        'content':
                        'Execution outcome is unknown because the session '
                        'process stopped. Verify external state before retrying.',
                        'is_error':
                        True,
                        'interrupted':
                        True,
                    })
                    results.add(call['id'])
        self.log.append({
            'role': 'assistant',
            'content': '[Interrupted: session process stopped]',
            'interrupted': True,
            'content_placeholder': True,
            'turn_id': last.get('turn_id'),
        })
        if open_task:
            self._task_event('interrupted', open_task['turn_id'])

    def _task_event(self, state, turn_id):
        self.log.record_input_event(
            {'task': {
                'turn_id': turn_id,
                'state': state
            }})

    def _record(self, item):
        self.log.record_input_event({'input': deepcopy(item)})

    def _notify(self):
        if self.on_change:
            self.on_change()

    def pending(self):
        return [
            deepcopy(item) for item in self.inputs.values()
            if item['state'] == 'pending'
        ]

    def validate_files(self, request):
        if self.workspace is None:
            return
        for file in (request.get('message') or {}).get('files') or []:
            try:
                path = self.workspace._resolve_safe(file['path'])
            except PermissionError:
                raise ValueError(
                    f'Attachment is outside the workspace: {file["path"]}'
                ) from None
            if not path.is_file():
                raise ValueError(
                    f'Attachment is no longer available: {file["path"]}')

    def _validate_delivery(self, items):
        for item in items:
            try:
                self.validate_files(item['request'])
            except ValueError as exc:
                item['error'] = str(exc)
                self.hold('unavailable')
                raise

    async def accept(self,
                     input_id: str,
                     request: dict,
                     prepare,
                     delivery: str = 'queue',
                     target: str | None = None):
        """Concurrent retries share preparation; disconnect cannot cancel it."""
        existing = self.inputs.get(input_id)
        if existing:
            if existing['request'] != request:
                raise InputConflict(
                    'Input ID already belongs to another message')
            return deepcopy(existing)
        inflight = self._preparing.get(input_id)
        if inflight:
            if inflight[0] != request:
                raise InputConflict(
                    'Input ID already belongs to another message')
            return deepcopy(await asyncio.shield(inflight[1]))
        if len(self.pending()) + len(self._preparing) >= self.MAX_PENDING:
            raise InputConflict('The pending input limit has been reached')
        if delivery == 'steer' and target != self.active_turn:
            raise InputConflict('The target task has ended; submit again')
        # Capture mode and target BEFORE asynchronous preparation.
        mode = delivery if self.active_turn else 'queue'
        hold_generation = self._hold_generation

        async def commit():
            try:
                self.validate_files(request)
                prepared = await prepare(request)
                if mode == 'steer' and target != self.active_turn:
                    raise InputConflict(
                        'The target task has ended; submit again')
                item = dict(
                    input_id=input_id,
                    request=deepcopy(request),
                    prepared=prepared,
                    delivery=mode,
                    target_turn_id=target if mode == 'steer' else None,
                    revision=1,
                    state='pending',
                    held=('stopped' if self.stopping or
                          hold_generation != self._hold_generation else None))
                self._record(item)
                self.inputs[input_id] = item
                self._notify()
                return deepcopy(item)
            finally:
                self._preparing.pop(input_id, None)

        task = asyncio.create_task(commit())
        self._preparing[input_id] = (deepcopy(request), task)
        # Retrieve exceptions even when the only HTTP waiter disconnected.
        task.add_done_callback(lambda t: None
                               if t.cancelled() else t.exception())
        return deepcopy(await asyncio.shield(task))

    def _editable(self, input_id, revision):
        item = self.inputs.get(input_id)
        if (not item or item['state'] != 'pending' or item.get('claimed')
                or item['revision'] != revision):
            raise InputConflict(
                'The message changed or has already been delivered')
        return item

    async def edit(self, input_id, revision, request, prepare):
        self._editable(input_id, revision)
        self.validate_files(request)
        prepared = await prepare(request)
        item = self._editable(input_id, revision)
        for key in ('model_id', 'reasoning_effort'):
            if key in item['prepared']:
                prepared[key] = item['prepared'][key]
        updated = {
            **item, 'request': deepcopy(request),
            'prepared': prepared,
            'revision': revision + 1
        }
        updated.pop('error', None)
        self._record(updated)
        self.inputs[input_id] = updated
        self._notify()
        return deepcopy(updated)

    def withdraw(self, input_id, revision):
        item = self._editable(input_id, revision)
        updated = {**item, 'state': 'cancelled', 'revision': revision + 1}
        self._record(updated)
        self.inputs[input_id] = updated
        self._notify()

    def start_next(self):
        if self.active_turn or self.stopping:
            return None
        for item in self.inputs.values():
            if item['state'] != 'pending' or item.get('held'):
                continue
            self._validate_delivery([item])
            self.active_turn = uuid4().hex
            self.active_input = item['input_id']
            self.segment_id = uuid4().hex
            self._task_event('started', self.active_turn)
            item['claimed'] = True
            self._notify()
            return deepcopy(item)
        return None

    def has_steering(self):
        return bool(self.active_turn) and any(
            item['state'] == 'pending' and not item.get('held')
            and item['delivery'] == 'steer'
            and item['target_turn_id'] == self.active_turn
            for item in self.inputs.values())

    def take_steering(self):
        items = [
            item for item in self.inputs.values() if item['state'] == 'pending'
            and not item.get('held') and item['delivery'] == 'steer'
            and item['target_turn_id'] == self.active_turn
        ]
        self._validate_delivery(items)
        for item in items:
            item['claimed'] = True
        return deepcopy(items)

    def append_message(self, row: dict):
        """Commit the canonical row before removing the pending representation."""
        row = dict(row)
        input_id = row.get('input_id')
        if row.get('role') == 'user' and not input_id and self.active_input:
            item = self.inputs[self.active_input]
            if item['state'] == 'pending':
                input_id = self.active_input
        item = self.inputs.get(input_id)
        if item and row.get('role') == 'user':
            if item['state'] == 'delivered':
                return
            row.update(
                input_id=input_id,
                delivery=item['delivery'],
                message_id=input_id,
                turn_id=self.active_turn)
            marker = item['prepared'].get('marker')
            if marker:
                self.log.record_skill_invocation(marker)
        row.setdefault('turn_id', self.active_turn)
        row.setdefault('message_id', uuid4().hex)
        row.setdefault('segment_id', self.segment_id)
        seq = self.log.append(row)
        if item and row.get('role') == 'user':
            item.update(
                state='delivered',
                turn_id=self.active_turn,
                message_id=row['message_id'])
            self._notify()
        return seq

    def finish(self):
        """The caller checks steering immediately before this synchronous commit."""
        if self.has_steering():
            return False
        if self.active_turn:
            self._task_event('completed', self.active_turn)
        self.active_turn = self.active_input = self.segment_id = None
        self._notify()
        return True

    def deliver_command(self, input_id):
        """Administrative slash commands are display-only, outside LLM context."""
        item = self.inputs[input_id]
        item.update(
            state='delivered',
            turn_id=self.active_turn,
            message_id=input_id,
            command_delivered=True)
        self._record(item)
        self._notify()

    def complete_command(self, input_id, text):
        self.log.record_input_event({
            'command_reply': {
                'input_id': input_id,
                'turn_id': self.active_turn,
                'message_id': self.segment_id,
                'content': text
            }
        })

    def hold(self, reason='stopped'):
        self.stopping = True
        self._hold_generation += 1
        for item in self.inputs.values():
            if item['state'] == 'pending':
                item['held'] = reason
                item.pop('claimed', None)
                self._record(item)
        self._notify()

    def stopped(self):
        if self.active_turn:
            self._task_event('interrupted', self.active_turn)
        self.active_turn = self.active_input = self.segment_id = None
        self.stopping = False
        self._notify()

    def resume(self):
        if self.stopping:
            raise InputConflict('The task is still stopping')
        for item in self.inputs.values():
            if item['state'] == 'pending' and item.get('held'):
                item.update(held=None, delivery='queue', target_turn_id=None)
                self._record(item)
        self._notify()

    async def close(self):
        tasks = [task for _, task in self._preparing.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
