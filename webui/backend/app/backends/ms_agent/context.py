"""Context operations use the SDK and the existing session/runtime owner."""
from __future__ import annotations

import asyncio

from app.backends.errors import Conflict, NotFound
from app.backends.ms_agent.common import find_session
from app.backends.ms_agent.runtime import registry, _settings_fingerprint


def status(session_id: str) -> dict:
    from app.backends.ms_agent import session_models
    from app.backends.ms_agent.models import generation_defaults

    found = find_session(session_id)
    if not found:
        raise NotFound('Conversation not found.')
    project, session, manager = found
    rt = registry.peek_exact(session_id)
    task = getattr(rt, 'context_task', None)
    operation = getattr(rt, 'context_state', None)
    path = manager.sessions_dir / session.id / f'{session.session_key}.jsonl'
    if not path.is_file():
        return {'snapshot': None, 'operation': operation, 'can_compact': False}
    log = manager.get_session_log(session)
    snapshot = log.get_metadata().get('context_snapshot')
    rows = log.get_visible_messages()
    try:
        _, model = session_models.prepare(project, session)
        defaults = generation_defaults(*model.key)
        revision = defaults.catalog.revision if defaults.catalog else None
        if snapshot and (snapshot.get('signature') != _settings_fingerprint(project, model)
                         or snapshot.get('catalog_revision') != revision
                         or snapshot.get('window_start') != log.last_consolidated
                         or snapshot.get('tail_seq') != (rows[-1]['seq'] if rows else -1)):
            snapshot = None
    except Exception:
        snapshot = None
    if not operation:
        operations = log.get_context_operations()
        operation = operations[-1] if operations else operation
        if operation and operation['status'] == 'running':
            operation = dict(operation, status='interrupted')
    return {'snapshot': snapshot, 'operation': operation,
            'can_compact': bool(rows) and not registry.is_running(session_id) and not (task and not task.done()),
            'pending': log.get_metadata().get('pending_context'),
            'resuming': bool(getattr(rt, 'context_resuming', False)),
            'busy': bool(task and not task.done()) or bool(getattr(rt, 'context_resuming', False))}


async def start(session_id: str) -> dict:
    found = find_session(session_id)
    if not found:
        raise NotFound('Conversation not found.')
    project, session, _ = found
    if registry.is_running(session_id):
        raise Conflict('Wait for the current turn to finish before compacting.')
    rt = await registry.get(project, session)
    if rt.turn_lock.locked():
        raise Conflict('A conversation or compaction is already running.')
    await rt.turn_lock.acquire()
    rt.context_state = {'status': 'running', 'trigger': 'manual'}
    rt.context_task = asyncio.create_task(_run(rt))
    return {'status': 'running'}


async def _run(rt) -> None:
    """Wait for the SDK input boundary; no fake prompt and no conversation call."""
    waiting = asyncio.create_task(rt.input_source.waiting.wait())
    try:
        done, _ = await asyncio.wait((waiting, rt.run_task), timeout=30,
                                     return_when=asyncio.FIRST_COMPLETED)
        if waiting not in done or rt.run_task.done():
            raise RuntimeError('Agent did not become ready for context compaction')
        result = await rt.agent.compact_context(force=True, trigger='manual')
        messages = result.pop('messages', None)
        if messages is not None:
            messages = await rt.agent.condense_memory(messages)
            await rt.agent.update_context_snapshot(messages)
        rt.context_state = result
    except asyncio.CancelledError:
        rt.context_state = {'status': 'cancelled', 'trigger': 'manual'}
        raise
    except Exception as error:
        rt.context_state = {'status': 'failed', 'trigger': 'manual',
                            'error_type': type(error).__name__}
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        rt.needs_rebuild = True
        rt.turn_lock.release()


async def retry(session_id: str) -> dict:
    """Continue the persisted request using the SDK's typed input operation."""
    from app.backends.ms_agent.chat import _acquire_live_runtime, _drain_abandoned_turn
    from ms_agent.ui.input import ResumeContext
    import time

    found = find_session(session_id)
    if not found:
        raise NotFound('Conversation not found.')
    project, session, manager = found
    if registry.is_running(session_id):
        raise Conflict('A conversation is already running.')
    pending = manager.get_session_log(session).get_metadata().get('pending_context')
    if not pending or pending.get('status') != 'paused':
        raise Conflict('No paused context request to resume.')
    rt = await _acquire_live_runtime(project, session)
    try:
        current = manager.get_session_log(session).get_metadata().get('pending_context')
        if not current or current.get('status') != 'paused':
            raise Conflict('The paused request has already been handled.')
        rt.context_resuming = True
        rt.sink.new_turn()
        rt.turn_user = None
        rt.turn_started_at = time.monotonic()
        await rt.enqueue(ResumeContext())
        async def drain():
            try:
                await _drain_abandoned_turn(rt, 0, session_id)
            finally:
                rt.context_resuming = False
        # Owned like the normal turn's background drain; aclose cancels it.
        rt.context_retry_task = asyncio.create_task(drain())
    except BaseException:
        rt.context_resuming = False
        rt.turn_lock.release()
        raise
    return {'status': 'running'}
