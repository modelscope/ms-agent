"""Read immutable conversation prefixes and their committed context views."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class InvalidForkPoint(ValueError):
    """The requested history cannot be safely continued."""


def read_records(source: Path | BinaryIO, after_seq: int | None = None,
                 *, strict: bool = False) -> list[dict]:
    if isinstance(source, Path):
        with source.open('rb') as stream:
            return read_records(stream, after_seq, strict=strict)
    records = []
    previous = -1
    for line in source:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('Invalid record')
            if row.get('_type') != 'metadata':
                seq = row.get('seq')
                if isinstance(seq, bool) or not isinstance(seq, int) or seq <= previous:
                    raise ValueError('Invalid sequence')
                previous = seq
        except (ValueError, UnicodeError):
            if strict or after_seq is not None:
                raise InvalidForkPoint('Conversation history is incomplete or damaged.') from None
            continue
        records.append(row)
        if after_seq is not None and row.get('seq') == after_seq:
            return records
    if after_seq is not None:
        raise InvalidForkPoint('The selected conversation position no longer exists.')
    return records


def committed_records(records: list[dict]) -> tuple[list[dict], int | None]:
    """Exclude unfinished new-format compactions; return the last saved start.

    Legacy compactions have no commit marker. Their saved view is contiguous
    after the event; callers validate completed turns before forking it.
    """
    accepted = set()
    pending: dict[str, tuple[dict, list[dict]]] = {}
    start = None
    legacy_pending = False
    for row in records:
        kind = row.get('_type')
        if kind == 'compaction_event':
            transaction = row.get('transaction_id')
            if transaction:
                pending[transaction] = (row, [])
                legacy_pending = False
            else:
                legacy_pending = True
        elif row.get('_compaction_id'):
            transaction = row['_compaction_id']
            if transaction in pending:
                pending[transaction][1].append(row)
        elif kind == 'compaction_commit':
            transaction = row.get('transaction_id')
            event, messages = pending.get(transaction, ({}, []))
            if (messages and len(messages) == event.get('message_count')
                    and messages[0]['seq'] == row.get('context_start')
                    and messages[-1]['seq'] == row.get('context_end')):
                accepted.add(transaction)
                start = row['context_start']
        elif legacy_pending:
            if row.get('_source') == 'compaction':
                start = row['seq']
            legacy_pending = False
    return ([r for r in records if not r.get('_compaction_id')
             or r['_compaction_id'] in accepted], start)


def context_messages(records: list[dict], start: int | None = None) -> list[dict]:
    from ms_agent.session.session_log import _merge_image_delivery

    records, saved_start = committed_records(records)
    messages = []
    for row in records:
        if row.get('_type') == 'image_delivery':
            _merge_image_delivery(messages, row)
        elif not row.get('_type') and row.get('role'):
            messages.append(deepcopy(row))
    start = saved_start if start is None else start
    return [r for r in messages if r.get('seq', 0) >= (start or 0)]


@dataclass(frozen=True)
class ForkPoint:
    after_seq: int
    assistant_seq: int
    context_start: int
    round: int
    state: dict


def fork_points(records: list[dict], *, require_checkpoint: bool = True) -> list[ForkPoint]:
    """Find successful user turns, including complete pre-checkpoint logs."""
    points: list[ForkPoint] = []
    pending: set[str] = set()
    has_user = False
    failed = False
    final = None
    rounds = 0
    saved_round = None
    context_start = 0
    state: dict = {}
    end = 0
    valid, _ = committed_records(records)
    accepted = {r.get('_compaction_id') for r in valid if r.get('_compaction_id')}
    legacy_compaction = False
    checkpoint = False
    required_from = next((r['checkpoint_from_seq'] for r in records
                          if r.get('_type') == 'metadata' and 'checkpoint_from_seq' in r), None)

    def finish():
        if (final is not None and has_user and not failed and not pending
                and (not require_checkpoint or checkpoint or required_from is None or final < required_from)):
            round_at_reply = saved_round if saved_round is not None else max(0, rounds - 1)
            points.append(ForkPoint(end, final, context_start, round_at_reply, dict(state)))

    for row in records:
        seq = row.get('seq', -1)
        kind = row.get('_type')
        source = row.get('_source')
        role = row.get('role')
        if kind == 'compaction_event':
            legacy_compaction = not row.get('transaction_id')
        if source == 'compaction':
            if legacy_compaction:
                context_start = seq
                legacy_compaction = False
            continue
        if kind == 'compaction_commit':
            if row.get('transaction_id') in accepted:
                context_start = row['context_start']
            if final is not None:
                end = seq
            continue
        if kind == 'metadata':
            continue
        if role == 'user':
            finish()
            has_user, failed, final, checkpoint = True, False, None, False
            pending.clear()
            state = {}
            saved_round = None
        elif role == 'assistant':
            rounds += 1
            failed |= bool(row.get('interrupted') or row.get('errored'))
            calls = row.get('tool_calls') or []
            if calls:
                for call in calls:
                    call_id = call.get('id')
                    if not call_id or call_id in pending:
                        failed = True
                    else:
                        pending.add(call_id)
                final = None
            elif has_user:
                final = seq
        elif role == 'tool':
            call_id = row.get('tool_call_id')
            if call_id not in pending:
                failed = True
            pending.discard(call_id)
        elif kind == 'error':
            failed = True
        elif kind == 'turn_checkpoint':
            checkpoint = True
            if row.get('assistant_seq') != final or row.get('status') != 'completed':
                failed = True
            context_start = row.get('context_start', context_start)
            saved_round = row.get('round')
            state = row.get('state') or {}
        # A skill invocation belongs to the next user input, not the old turn.
        if kind != 'skill_invocation':
            end = seq
    finish()
    return points


def select_point(records: list[dict], after_seq: int) -> ForkPoint:
    points = fork_points(records)
    if not points or points[-1].after_seq != after_seq:
        raise InvalidForkPoint('Select a normally completed reply to branch from.')
    point = points[-1]
    visible = context_messages(records, point.context_start)
    if not visible or visible[-1].get('role') != 'assistant' or visible[-1].get('tool_calls'):
        raise InvalidForkPoint('The saved context at this position is incomplete.')
    pending = set()
    has_user = False
    for row in visible:
        role = row.get('role')
        if role == 'tool':
            call_id = row.get('tool_call_id')
            if call_id not in pending:
                raise InvalidForkPoint('The saved context has an unmatched tool result.')
            pending.remove(call_id)
        else:
            if pending:
                raise InvalidForkPoint('The saved context has missing tool results.')
            has_user |= role == 'user'
            for call in row.get('tool_calls') or []:
                call_id = call.get('id')
                if not call_id or call_id in pending:
                    raise InvalidForkPoint('The saved context has invalid tool calls.')
                pending.add(call_id)
    if not has_user or pending:
        raise InvalidForkPoint('The saved context at this position is incomplete.')
    return point
