"""Session transport: one execution owner, independent reconnectable viewers.

Scheduling and durable state live in the SDK controller. This adapter reuses
the existing runtime, stream mapper, history reconstruction and title handling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from copy import deepcopy
from dataclasses import asdict
from uuid import uuid4

from app.backends.errors import BadRequest, Conflict, NotFound
from app.backends.ms_agent.common import find_session, home, sm_for
from app.schemas.chat import ChatRequest
from ms_agent.config.interaction_settings import InteractionSettings
from ms_agent.session.input_controller import InputConflict, SessionInputController

logger = logging.getLogger(__name__)
conversations: dict[str, Conversation] = {}


class Conversation:
    def __init__(self, project, session):
        self.project, self.session = project, session
        self.epoch = uuid4().hex
        self.sequence = 0
        self.events = deque(maxlen=2048)
        self.pulse = asyncio.Event()
        self.worker = None
        self.viewers = 0
        self.last_active = time.monotonic()
        self.turn_id = None
        self.started_at = None
        self.active_frames = []
        self.history = self._history()
        log = sm_for(project).get_session_log(session)
        from ms_agent.project import Workspace
        self.controller = SessionInputController(log, workspace=Workspace(project.path))
        self.controller.on_change = self._changed

    def _history(self):
        from app.backends.ms_agent.sessions import list_messages
        return [m.model_dump(mode='json') for m in list_messages(self.session.id)]

    def state(self):
        # Prepared prompts/hook context are SDK-only; never send them to the UI.
        pending = [{k: deepcopy(v) for k, v in item.items()
                    if k not in ('prepared', 'claimed')}
                   for item in self.controller.pending()]
        return dict(pending=pending, turn_id=self.turn_id or self.controller.active_turn,
                    running=bool(self.turn_id), stopping=self.controller.stopping)

    def publish(self, event):
        self.sequence += 1
        envelope = {**event, 'cursor': f'{self.epoch}:{self.sequence}'}
        self.events.append(envelope)
        self.pulse.set()

    def _changed(self):
        self.publish({'type': 'state', **self.state()})

    def snapshot(self):
        if not self.turn_id:
            self.history = self._history()
        frames = deepcopy(self.active_frames)
        if self.started_at is not None and self.turn_id:
            frames.append({'type': 'turn', 'content': '', 'meta': {
                'elapsed_ms': int((time.monotonic() - self.started_at) * 1000)}})
        return dict(type='snapshot', cursor=f'{self.epoch}:{self.sequence}',
                    session_id=self.session.id, project_id=self.project.id,
                    history=self.history, frames=frames,
                    **self.state())

    async def prepare(self, request):
        from app.backends.ms_agent import chat
        from app.backends.ms_agent.runtime import registry
        from ms_agent.hooks.context import apply_hook_result_to_messages
        from ms_agent.llm.utils import Message
        req = ChatRequest.model_validate(request)
        if req.message is None or req.message.role != 'user':
            raise BadRequest('A user message is required')
        prompt, attachments = chat._compose_turn(req.message)
        typed, skills = chat._content_parts(req.message)
        if not prompt and not skills:
            raise BadRequest('The message is empty')
        rt = await registry.get(self.project, self.session)
        rt.agent._input_controller = self.controller
        # On cold build the SDK initializes hooks/tools before reading input.
        if not getattr(rt.agent, 'session_log', None):
            waiting = asyncio.create_task(rt.input_source.waiting.wait())
            try:
                done, _ = await asyncio.wait(
                    [waiting, rt.run_task], return_when=asyncio.FIRST_COMPLETED)
                if waiting not in done:
                    raise BadRequest('The agent could not initialize')
            finally:
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
        if rt.input_source.waiting.is_set():
            chat._sync_runtime_skills(rt, self.project)
        router = rt.agent._get_command_router()
        command = router.resolve(router.parse_input(prompt)[0]) if prompt.startswith('/') else None
        if command is not None and self.controller.active_turn:
            raise Conflict('Administrative commands are available after the current task finishes')
        marker = None
        if skills or '/' in prompt:
            expanded = chat._expand_skill_request(rt, prompt, skills)
            if expanded:
                kind, prompt, marker = expanded
                if kind != 'submit':
                    raise BadRequest('This command cannot be submitted as a message')
        # Always preserve the original display text, including attachment refs.
        marker = marker or {'original_text': chat._compose_turn(req.message)[0],
                            'skill_ids': skills}
        if isinstance(req.message.content, list):
            marker['segments'] = [s.model_dump() for s in req.message.content]
        message = Message(role='user', content=prompt)
        hooks = getattr(rt.agent, '_hook_runtime', None)
        if hooks is not None and not hooks.is_empty and command is None:
            result = await hooks.run_user_prompt_submit(prompt)
            if result.action in ('deny', 'block'):
                raise BadRequest(result.reason or 'The input hook declined this message')
            apply_hook_result_to_messages([message], result, hook_event='UserPromptSubmit')
        from app.backends.ms_agent import session_models
        from app.backends.ms_agent.mapping import encode_model_id
        current, snapshot = session_models.prepare(self.project, self.session)
        model_id = encode_model_id(*snapshot.key)
        effort = current.reasoning_efforts[snapshot.key[0]][snapshot.key[1]]
        return dict(prompt=prompt, attachments=attachments, marker=marker,
                    command=command is not None,
                    model_id=model_id, reasoning_effort=effort,
                    hook_attachments=[asdict(a) for a in message.hook_attachments or []])

    def kick(self):
        self.last_active = time.monotonic()
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._run())

    async def _run(self):
        from app.backends.ms_agent.chat import run_turn, _LOCK_ACQUIRE_TIMEOUT
        from app.backends.ms_agent.runtime import registry
        try:
            while True:
                # Manual compaction/context retry can own the runtime without
                # an inbox task. Do not assign the next task's identity to SDK
                # messages that still belong to that operation.
                rt = registry.peek_exact(self.session.id)
                if rt is not None and rt.turn_lock.locked():
                    await asyncio.wait_for(rt.turn_lock.acquire(), _LOCK_ACQUIRE_TIMEOUT)
                    rt.turn_lock.release()
                    continue
                item = self.controller.start_next()
                if item is None:
                    break
                self.history = self._history()
                self.turn_id = self.controller.active_turn
                self.started_at = time.monotonic()
                self.active_frames = []
                self.publish({'type': 'begin', 'turn_id': self.turn_id})
                # A queue item keeps its selected model even if settings changed
                # while it waited. The normal SDK resolver revalidates access.
                from app.backends.ms_agent import session_models
                from app.backends.ms_agent.mapping import decode_model_id
                current = sm_for(self.project).get(self.session.id)
                model_id = item['prepared'].get('model_id')
                if model_id:
                    key = decode_model_id(model_id)
                    session_models.validate_selection(*key)
                    efforts = deepcopy(current.reasoning_efforts)
                    efforts.setdefault(key[0], {})[key[1]] = item['prepared']['reasoning_effort']
                    self.session = sm_for(self.project).update(
                        current.id, model_provider=key[0], model=key[1], reasoning_efforts=efforts)
                is_command = item['prepared'].get('command')
                if is_command:
                    self.controller.deliver_command(item['input_id'])
                    chunk = {'type': 'input', 'content': '', 'meta': {
                        'input_id': item['input_id'], 'turn_id': self.turn_id,
                        'segment_id': self.controller.segment_id,
                        'message': item['request']['message']}}
                    self._append_frame(chunk)
                    self.publish({'type': 'chunk', 'chunk': chunk, 'turn_id': self.turn_id})
                req = ChatRequest.model_validate({**item['request'],
                                                  'session_id': self.session.id})
                failed = False
                async for frame in run_turn(req, prepared=item['prepared']):
                    chunk = json.loads(frame['data'])
                    if chunk['type'] == 'done' and not self.viewers and not self.controller.stopping:
                        from app.backends.ms_agent import sidecar
                        sidecar.merge('sessions', self.session.id, {'unread': True})
                    failed = failed or chunk['type'] == 'error'
                    self._append_frame(chunk)
                    self.publish({'type': 'chunk', 'chunk': chunk,
                                  'turn_id': self.turn_id})
                if is_command:
                    self.controller.complete_command(item['input_id'], ''.join(
                        frame['content'] for frame in self.active_frames if frame['type'] == 'text'))
                if failed:
                    self.controller.hold('error')
                    self.controller.stopped()
                elif self.controller.active_turn:
                    # EOF/max-round completion paths do not pass after_tool_call.
                    if not self.controller.finish():
                        self.controller.hold('error')
                        self.controller.stopped()
                self.turn_id = None
                self.active_frames = []
                self.history = self._history()
                self.publish(self.snapshot())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception('Conversation task failed')
            self.controller.hold('error')
            self.controller.stopped()
            self.turn_id = None
            self.active_frames = []
            self.publish(self.snapshot())
            self.publish({'type': 'failure', 'message': str(exc)})
        finally:
            self.last_active = time.monotonic()

    def _append_frame(self, chunk):
        # Snapshot buffers grow with content, not token count. Event replay is
        # bounded independently; an old cursor falls back to this snapshot.
        if chunk['type'] == 'turn':
            return  # snapshot() supplies the current elapsed time once
        previous = self.active_frames[-1] if self.active_frames else None
        if (previous and chunk['type'] in ('text', 'thought')
                and previous['type'] == chunk['type']
                and (previous.get('meta') == chunk.get('meta') or (
                    chunk['type'] == 'thought'
                    and previous.get('meta', {}).get('block') == chunk.get('meta', {}).get('block')))):
            previous['content'] += chunk['content']
            previous['meta'] = {**previous.get('meta', {}), **chunk.get('meta', {})}
        else:
            self.active_frames.append(deepcopy(chunk))

    async def subscribe(self, cursor=None):
        self.viewers += 1
        try:
            async for event in self._subscribe(cursor):
                yield event
        finally:
            self.viewers -= 1
            self.last_active = time.monotonic()

    async def _subscribe(self, cursor=None):
        position = None
        if cursor:
            try:
                epoch, seq = cursor.split(':')
                if epoch == self.epoch:
                    position = int(seq)
            except (ValueError, TypeError):
                pass
        while True:
            earliest = self.sequence - len(self.events)
            if position is None or position < earliest or position > self.sequence:
                snapshot = self.snapshot()
                position = self.sequence
                yield {'id': snapshot['cursor'], 'data': json.dumps(snapshot)}
            for event in list(self.events):
                sequence = int(event['cursor'].rsplit(':', 1)[1])
                if sequence > position:
                    position = sequence
                    yield {'id': event['cursor'], 'data': json.dumps(event)}
            self.pulse.clear()
            if position != self.sequence:
                continue
            await self.pulse.wait()


def get(session_id):
    found = find_session(session_id)
    if not found:
        raise NotFound('Conversation not found')
    if session_id not in conversations:
        conversations[session_id] = Conversation(found[0], found[1])
    conversations[session_id].last_active = time.monotonic()
    return conversations[session_id]


async def submit(req: ChatRequest):
    from app.backends.ms_agent.chat import _resolve_or_create
    if not req.input_id:
        req = req.model_copy(update={'input_id': uuid4().hex})
    project, session = _resolve_or_create(req)
    conversation = get(session.id)
    request = req.model_dump(exclude={'input_id', 'expected_turn_id', 'session_id', 'project_id'})
    mode = InteractionSettings(home()).get()
    if mode == 'steer' and conversation.controller.active_turn:
        if req.model_id or req.reasoning_effort:
            raise Conflict('An in-task input cannot change the model')
    try:
        receipt = await conversation.controller.accept(
            req.input_id, request, conversation.prepare, mode, req.expected_turn_id)
    except InputConflict as exc:
        raise Conflict(str(exc)) from None
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    conversation.kick()
    return dict(session_id=session.id, project_id=project.id,
                cursor=f'{conversation.epoch}:{conversation.sequence}',
                input={k: v for k, v in receipt.items() if k != 'prepared'},
                **conversation.state())


async def interrupt(session_id, expected_turn_id=None):
    from app.backends.ms_agent.runtime import registry
    conversation = get(session_id)
    if expected_turn_id and expected_turn_id != conversation.controller.active_turn:
        raise Conflict('The target task has ended')
    conversation.controller.hold('stopped')
    try:
        # Stop also owns the startup window before the SDK has a live turn.
        # Cancel admission-to-execution first, so it cannot rebuild a runtime
        # after registry.interrupt has closed the previous one.
        if conversation.worker and not conversation.worker.done():
            conversation.worker.cancel()
            await asyncio.gather(conversation.worker, return_exceptions=True)
        return await registry.interrupt(session_id)
    finally:
        conversation.controller.stopped()
        conversation.turn_id = None
        conversation.active_frames = []
        conversation.publish(conversation.snapshot())


async def close_all():
    for session_id in list(conversations):
        await discard(session_id)


async def discard(session_id):
    conversation = conversations.pop(session_id, None)
    if conversation is None:
        return
    conversation.controller.hold('restart')
    await conversation.controller.close()
    if conversation.worker and not conversation.worker.done():
        conversation.worker.cancel()
        await asyncio.gather(conversation.worker, return_exceptions=True)


def sweep_idle(ttl, limit):
    from app.backends.ms_agent.runtime import registry
    idle = sorted((c for c in conversations.values()
                   if not c.viewers and not c.controller._preparing
                   and registry.peek_exact(c.session.id) is None
                   and (c.worker is None or c.worker.done())),
                  key=lambda c: c.last_active)
    overflow = max(0, len(conversations) - limit)
    for index, conversation in enumerate(idle):
        if index < overflow or time.monotonic() - conversation.last_active > ttl:
            conversations.pop(conversation.session.id, None)
