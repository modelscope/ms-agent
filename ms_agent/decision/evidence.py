"""Bounded, source-linked evidence reconstructed from original session rows."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


def text(value) -> str:
    from ms_agent.llm.message_text import flatten_message_text
    return flatten_message_text(value)


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False,
                   default=str).encode()).hexdigest()[:24]


def original_rows(rows):
    return [
        r for r in rows if r.get('role') and r.get('_source') != 'compaction'
    ]


def call_parts(call):
    function = call.get('function') or {}
    name = call.get('tool_name') or function.get('name') or ''
    args = call.get('arguments', function.get('arguments', {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            pass
    return name, args


def status(row):
    if row.get('is_error'):
        return 'error'
    try:
        body = json.loads(text(row.get('content', '')))
    except (ValueError, TypeError):
        return 'unknown'
    if not isinstance(body, dict):
        return 'unknown'
    code = body.get('exit_code', body.get('returncode',
                                          body.get('return_code')))
    if isinstance(code, int) and not isinstance(code, bool):
        return 'success' if code == 0 else 'error'
    if (body.get('status') in ('error', 'failed')
            or body.get('is_error') is True or body.get('success') is False):
        return 'error'
    if body.get('status') in ('ok', 'success') or body.get('success') is True:
        return 'success'
    return 'unknown'


@dataclass
class EvidenceSnapshot:
    task_id: str
    objective: str
    tools: list[dict] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    covered: bool = True

    @property
    def protected_seqs(self):
        return {e['seq'] for e in self.unresolved}

    @property
    def tool_round_count(self):
        return len({e['round_id'] for e in self.tools})

    def state(self):
        recent = self.tools[-8:]
        selected = {e['id']: e for e in [*self.unresolved[-12:], *recent]}
        return {
            'objective': self.objective,
            'evidence': list(selected.values()),
            'coverage_complete': self.covered
        }


def evidence(rows) -> EvidenceSnapshot:
    rows = original_rows(rows)
    start = next(
        (i for i in range(len(rows) - 1, -1, -1)
         if rows[i].get('role') == 'user' and not rows[i].get(
             'decision_feedback') and not rows[i].get('context_summary')), 0)
    task = rows[start] if rows else {}
    objective = text(task.get('content', ''))
    result = EvidenceSnapshot(
        str(task.get('seq', '0')),
        objective[:12000],
        covered=len(objective) <= 12000)
    calls, rounds, unresolved = {}, {}, {}
    for row in rows[start:]:
        for call in row.get('tool_calls') or []:
            calls[call.get('id')] = call_parts(call)
            rounds[call.get('id')] = row.get('origin_seq', row.get('seq'))
        if row.get('role') != 'tool':
            continue
        name, args = calls.get(
            row.get('tool_call_id'), (row.get('name', ''), {}))
        body = text(row.get('content', ''))
        seq = row.get('origin_seq', row.get('seq'))
        # Without the original call, matching by tool name alone could hide
        # an unrelated failure when another invocation succeeds.
        key = digest([name, args] if row.get('tool_call_id') in
                     calls else [name, seq])
        entry = {
            'id':
            f'e{seq}',
            'seq':
            seq,
            'tool':
            name,
            'round_id':
            rounds.get(row.get('tool_call_id'), seq),
            'arguments':
            json.dumps(args, ensure_ascii=False)[:2000],
            'status':
            status(row),
            'excerpt':
            body[:1600] + (body[-800:] if len(body) > 2400 else body[1600:]),
            'complete':
            len(body) <= 2400,
            'action_key':
            key,
            'result_hash':
            digest(body)
        }
        result.tools.append(entry)
        if entry['status'] == 'error':
            unresolved[key] = entry
        elif entry['status'] == 'success':
            unresolved.pop(key, None)
    result.unresolved = list(unresolved.values())
    if len(result.unresolved) > 12:
        result.covered = False
    return result
