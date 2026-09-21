"""Create independent sessions from a validated, immutable history prefix."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path

from ms_agent.project.types import Session, _now_iso
from ms_agent.session.replay import InvalidForkPoint, read_records, select_point
from ms_agent.utils.atomic_file import atomic_write_json


def _previous_request(manager, source_id, after_seq, request_id):
    if not request_id:
        return None
    for session in manager.list():
        origin = session.forked_from or {}
        if origin.get('request_id') == request_id:
            if origin.get('session_id') != source_id or origin.get('after_seq') != after_seq:
                raise InvalidForkPoint('This request was already used for a different branch.')
            return session
    return None


def _copy_plan(records: list[dict], directory: Path) -> None:
    calls = set()
    todos = None
    for row in records:
        if row.get('_source') == 'compaction':
            continue
        for call in row.get('tool_calls') or []:
            function = call.get('function') or {}
            if (call.get('tool_name') or function.get('name')) == 'todo_list---todo_write':
                calls.add(call.get('id'))
        if row.get('role') == 'tool' and row.get('tool_call_id') in calls:
            try:
                result = json.loads(row.get('content', ''))
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict) and result.get('status') == 'ok' and isinstance(result.get('todos'), list):
                todos = result['todos']
    if todos is not None:
        from ms_agent.tools.todolist_tool import TodoListTool
        plan = {'schema_version': 1, 'updated_at': _now_iso(), 'todos': todos}
        atomic_write_json(directory / 'plan.json', plan)
        (directory / 'plan.md').write_text(
            TodoListTool._render_plan_md_text(plan), encoding='utf-8')


def fork_session(manager, session_id: str, *, after_seq: int,
                 name: str | None = None, request_id: str | None = None) -> Session:
    if (not session_id or session_id in ('.', '..') or Path(session_id).name != session_id
            or isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0):
        raise InvalidForkPoint('Invalid conversation position.')
    if request_id is not None and (not request_id.strip() or len(request_id) > 128):
        raise InvalidForkPoint('Invalid branch request identifier.')
    if name is not None and (not name.strip() or len(name) > 160):
        raise InvalidForkPoint('Branch titles must contain 1 to 160 characters.')
    with manager.transaction_lock():
        manager._check_project()
        previous = _previous_request(manager, session_id, after_seq, request_id)
        if previous:
            return previous
        source = manager.get(session_id)
        if source is None:
            raise FileNotFoundError('Source conversation not found.')
        path = manager.sessions_dir / source.id / f'{source.session_key}.jsonl'
        stream = path.open('rb')
        identity = os.fstat(stream.fileno())
    with stream:
        records = read_records(stream, after_seq, strict=True)
        length = stream.tell()
        stream.seek(0)
        digest = hashlib.sha256(stream.read(length)).digest()
    point = select_point(records, after_seq)
    stage_root = manager.sessions_dir.parent / '.fork-staging'
    stage_root.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(dir=stage_root))
    try:
        child_id = uuid.uuid4().hex[:12]
        child_key = f'session_{child_id}'
        now = _now_iso()
        header = {'_type': 'metadata', 'session_key': child_key, 'created_at': now,
                  'checkpoint_from_seq': after_seq + 1}
        log_path = stage / f'{child_key}.jsonl'
        with log_path.open('w', encoding='utf-8') as dest:
            for row in [header, *[r for r in records if r.get('_type') != 'metadata']]:
                dest.write(json.dumps(row, ensure_ascii=False) + '\n')
            dest.flush()
            os.fsync(dest.fileno())
        atomic_write_json(stage / f'{child_key}.meta.json', {
            **header, 'last_consolidated': point.context_start,
            'round': point.round, 'status': 'idle',
            'active_model': point.state.get('active_model', ''),
            'fork_after_seq': after_seq,
        }, fsync=True)
        for key in ('prompt_surface', 'skill_surface'):
            if isinstance(point.state.get(key), dict):
                atomic_write_json(stage / f'{key}.json', point.state[key], fsync=True)
        _copy_plan(records, stage)
        with manager.transaction_lock():
            manager._check_project()
            previous = _previous_request(manager, session_id, after_seq, request_id)
            if previous:
                return previous
            if manager.get(session_id) is None:
                raise FileNotFoundError('Source conversation was deleted.')
            with path.open('rb') as current:
                stat = os.fstat(current.fileno())
                if ((stat.st_dev, stat.st_ino) != (identity.st_dev, identity.st_ino)
                        or hashlib.sha256(current.read(length)).digest() != digest):
                    raise InvalidForkPoint('Source history changed. Reload before branching.')
            source_origin = source.forked_from or {}
            group = source_origin.get('group_id', source.id)
            base_name = source_origin.get('base_name', source.name)
            counter_path = stage_root / 'indices.json'
            from ms_agent.project.store import JSONFileStore
            counters = JSONFileStore(counter_path).read() or {}
            existing = [int((s.forked_from or {}).get('index', 1)) for s in manager.list()
                        if (s.forked_from or {}).get('group_id') == group]
            index = max([1, counters.get(group, 1), *existing]) + 1
            counters[group] = index
            atomic_write_json(counter_path, counters, fsync=True)
            title = name.strip() if name else f'{base_name[:150]} ({index})'
            child = Session(
                id=child_id, project_id=source.project_id, name=title,
                session_key=child_key, model=source.model, model_provider=source.model_provider,
                forked_from={'session_id': source.id, 'title': source.name,
                             'after_seq': after_seq, 'assistant_seq': point.assistant_seq,
                             'group_id': group, 'base_name': base_name, 'index': index,
                             'request_id': request_id},
            )
            atomic_write_json(stage / manager.META_FILE, asdict(child), fsync=True)
            os.rename(stage, manager.sessions_dir / child.id)
            return child
    finally:
        if stage.exists():
            shutil.rmtree(stage)
