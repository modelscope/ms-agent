"""Resuming an interrupted JSONL write must preserve the next message."""
import json

import pytest

from ms_agent.session.session_log import SessionLog


@pytest.mark.parametrize('tail', ['clean', 'partial_json', 'partial_utf8', 'complete'])
@pytest.mark.parametrize('keep_sidecar', [True, False])
def test_resume_after_unterminated_record(tmp_path, tail, keep_sidecar):
    log = SessionLog(tmp_path, 'recovery')
    log.append({'role': 'user', 'content': '之前'})
    path = tmp_path / 'recovery.jsonl'
    if tail == 'partial_json':
        suffix = b'{"role":"assistant","content":"unfinished'
    elif tail == 'partial_utf8':
        suffix = b'{"role":"assistant","content":"\xe4\xb8'
    elif tail == 'complete':
        suffix = json.dumps({'role': 'assistant', 'content': 'Complete', 'seq': 1}).encode()
    else:
        suffix = b''
    with path.open('ab') as file:
        file.write(suffix)
    original = path.read_bytes()
    if not keep_sidecar:
        (tmp_path / 'recovery.meta.json').unlink()

    resumed = SessionLog(tmp_path, 'recovery')
    expected_seq = 2 if tail == 'complete' else 1
    assert resumed.append({'role': 'user', 'content': 'After recovery'}) == expected_seq
    resumed.record_compaction({'strategy': 'test'})

    reopened = SessionLog(tmp_path, 'recovery')
    messages = reopened.get_all_messages()
    expected = ['之前', 'Complete', 'After recovery'] if tail == 'complete' else ['之前', 'After recovery']
    assert [message['content'] for message in messages] == expected
    assert [message['seq'] for message in messages] == list(range(expected_seq + 1))
    assert reopened.get_compaction_events()[0]['strategy'] == 'test'
    assert reopened.get_errors() == []
    assert reopened.get_permissions() == []
    assert reopened.get_loop_ends() == []
    assert reopened.get_skill_invocations() == []
    assert path.read_bytes().startswith(original)
    assert reopened.append({'role': 'user', 'content': 'Next'}) == expected_seq + 2
