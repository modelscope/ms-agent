"""build_partial_round_records: protocol-valid sealing of an interrupted round.

Pure-function tests over the _msg_to_dict-shaped rows that run_loop's
cancellation handler feeds in. Each case mirrors a real interruption point:
mid-text stream, mid-reasoning, mid-tool-execution, truncated openai tool-call
deltas, and cancel-before-first-chunk.
"""
from ms_agent.agent.llm_agent import (INTERRUPTED_PLACEHOLDER,
                                      build_partial_round_records)


def test_empty_segment_seals_with_placeholder():
    # Cancelled before the first chunk: nothing streamed, but the turn must
    # read as closed (a dangling user row would be re-answered on resume).
    records = build_partial_round_records([])
    assert records == [{
        'role': 'assistant',
        'content': INTERRUPTED_PLACEHOLDER,
        'content_placeholder': True,
        'interrupted': True,
    }]


def test_partial_round_preserves_reasoning_duration():
    # When the elapsed thinking time was stamped before cancellation, the
    # interrupted row keeps `reasoning_duration` (so replay shows "thought Ns",
    # not 0s) even as the reasoning text moves to the display-only key.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '',
         'reasoning_content': '思考中…', 'reasoning_duration': 7},
    ])
    rec = records[0]
    assert rec['interrupted_reasoning'] == '思考中…'
    assert rec['reasoning_duration'] == 7


def test_partial_text_kept_verbatim_and_flagged():
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '写到一半的回答'},
    ])
    assert len(records) == 1
    rec = records[0]
    assert rec['content'] == '写到一半的回答'  # content never mutated
    assert rec['interrupted'] is True


def test_unsigned_reasoning_moves_to_display_only_key():
    # Interrupted thinking has no signature (assigned only at message_stop);
    # replaying it on the Anthropic protocol would 400 — keep it for the UI only.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '', 'reasoning_content': '思考中…'},
    ])
    rec = records[0]
    assert 'reasoning_content' not in rec
    assert rec['interrupted_reasoning'] == '思考中…'
    assert rec['content'] == INTERRUPTED_PLACEHOLDER  # no visible content
    assert rec['content_placeholder'] is True  # marked as synthetic filler


def test_signed_reasoning_stays_replayable():
    records = build_partial_round_records([
        {'role': 'assistant', 'content': 'ok', 'reasoning_content': 'r',
         'reasoning_signature': 'sig'},
    ])
    rec = records[0]
    assert rec['reasoning_content'] == 'r'
    assert 'interrupted_reasoning' not in rec


def test_mid_tool_execution_synthesizes_results():
    # Assistant finalized with two tool calls; cancelled while tools ran, so no
    # tool rows exist. Both transports require a result row per call id.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'tool_name': 'file_system---write_file',
             'arguments': '{"path": "a.md"}'},
            {'id': 'c2', 'tool_name': 'code_executor---shell_executor',
             'arguments': '{"command": "ls"}'},
        ]},
    ])
    assert [r['role'] for r in records] == ['assistant', 'tool', 'tool']
    assistant = records[0]
    assert len(assistant['tool_calls']) == 2
    assert assistant['content'] == ''  # tool_calls kept -> no placeholder needed
    for rec, cid, name in [(records[1], 'c1', 'file_system---write_file'),
                           (records[2], 'c2', 'code_executor---shell_executor')]:
        assert rec['tool_call_id'] == cid and rec['name'] == name
        assert rec['is_error'] is True and rec['interrupted'] is True
        assert 'Interrupted' in rec['content']


def test_truncated_arguments_dropped_and_placeholder_applied():
    # openai-compat interrupt can leave a half-streamed arguments JSON; such a
    # call never executed and must not be replayed as a tool_use.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'tool_name': 't', 'arguments': '{"path": "a.m'},
        ]},
    ])
    assert len(records) == 1  # no synthesized result for a dropped call
    rec = records[0]
    assert 'tool_calls' not in rec
    assert rec['content'] == INTERRUPTED_PLACEHOLDER
    assert rec['content_placeholder'] is True


def test_mixed_valid_and_truncated_calls():
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '先做两件事', 'tool_calls': [
            {'id': 'c1', 'tool_name': 'ok_tool', 'arguments': '{}'},
            {'id': 'c2', 'tool_name': 'bad_tool', 'arguments': '{"x": '},
            {'tool_name': 'no_id_tool', 'arguments': '{}'},
        ]},
    ])
    assistant = records[0]
    assert [tc['id'] for tc in assistant['tool_calls']] == ['c1']
    assert [r['tool_call_id'] for r in records[1:]] == ['c1']


def test_real_result_in_segment_not_duplicated():
    # If a genuine tool result row somehow made it into the segment, its call
    # must not also get a synthesized result.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'tool_name': 't', 'arguments': '{}'},
        ]},
        {'role': 'tool', 'content': 'real output', 'tool_call_id': 'c1',
         'name': 't'},
    ])
    roles = [r['role'] for r in records]
    assert roles == ['assistant', 'tool']  # pass-through, no synthesis
    assert records[1]['content'] == 'real output'
    assert records[1]['interrupted'] is True


def test_dict_arguments_accepted():
    # Some paths carry already-parsed dict arguments.
    records = build_partial_round_records([
        {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'tool_name': 't', 'arguments': {'a': 1}},
        ]},
    ])
    assert records[0]['tool_calls'][0]['arguments'] == {'a': 1}
    assert records[1]['role'] == 'tool'


def _persisted_reasoning_duration(reasoning_started_at, last_reasoning_duration):
    """Run the real _persist_partial_round against a minimal stub and return the
    reasoning_duration stamped on the persisted partial-reasoning row (or None)."""
    from ms_agent.agent.llm_agent import LLMAgent
    from ms_agent.llm.utils import Message

    class _Log:

        def __init__(self):
            self.rows = []

        def append(self, rec):
            self.rows.append(rec)
            return len(self.rows)

    stub = LLMAgent.__new__(LLMAgent)
    stub.session_log = _Log()
    stub._reasoning_started_at = reasoning_started_at
    stub._last_reasoning_duration = last_reasoning_duration
    # Thinking finished (has reasoning_content) but no _reasoning_duration yet:
    # handle_new_response never ran because the turn was cancelled.
    msg = Message(role='assistant', content='正文写到一半',
                  reasoning_content='想了很久…')
    LLMAgent._persist_partial_round(stub, [msg], 0)
    asst = [r for r in stub.session_log.rows
            if r.get('role') == 'assistant'][-1]
    return asst.get('reasoning_duration')


def test_reasoning_duration_kept_when_cancelled_during_body():
    # Reasoning ENDED, cancel hit during body streaming: _reasoning_started_at is
    # None, elapsed parked in _last_reasoning_duration. Must still persist it
    # (else replay shows "thought 0s").
    assert _persisted_reasoning_duration(None, 7) == 7


def test_reasoning_duration_finalized_when_cancelled_mid_reasoning():
    # Cancelled mid-reasoning: _reasoning_started_at still set → finalize now.
    import time
    dur = _persisted_reasoning_duration(time.monotonic() - 3.0, None)
    assert dur is not None and dur >= 2


# --- sealing a round that RAISED (not a user Stop) -----------------------


def test_errored_marker_replaces_interrupted():
    # run_loop's exception handler seals with marker='errored'. UIs badge
    # `interrupted` as a user Stop, so an API failure must not borrow that key.
    records = build_partial_round_records([], marker='errored')
    assert records == [{
        'role': 'assistant',
        'content': INTERRUPTED_PLACEHOLDER,
        'content_placeholder': True,
        'errored': True,
    }]
    assert 'interrupted' not in records[0]


def test_errored_marker_applies_to_synthesized_tool_results():
    records = build_partial_round_records(
        [{'role': 'assistant', 'content': '',
          'tool_calls': [{'id': 'c1', 'arguments': '{}', 'tool_name': 'grep'}]}],
        marker='errored')
    assert [r['role'] for r in records] == ['assistant', 'tool']
    assert all(r.get('errored') is True for r in records)
    assert not any('interrupted' in r for r in records)


def test_error_seal_closes_dangling_tool_tail():
    """The regression that made failed turns look like an infinite loop.

    A raised turn used to leave the log tail on a `tool` row. run_loop's resume
    guard only skips the model call when the tail is `assistant`, so the next
    request replayed the same round with the same failing context and never
    drained the queued prompt — every resend was silently dropped.
    """
    from ms_agent.agent.llm_agent import LLMAgent

    class _Log:

        def __init__(self, rows):
            self.rows = list(rows)

        def append(self, rec):
            self.rows.append(rec)
            return len(self.rows)

    # Tail as persisted by the round that then blew up on the next LLM call.
    stub = LLMAgent.__new__(LLMAgent)
    stub.session_log = _Log([
        {'role': 'user', 'content': '搜一下今天的热点新闻'},
        {'role': 'assistant', 'content': '',
         'tool_calls': [{'id': 'c1', 'arguments': '{}', 'tool_name': 'search'}]},
        {'role': 'tool', 'content': 'results', 'tool_call_id': 'c1'},
    ])
    stub._reasoning_started_at = None
    stub._last_reasoning_duration = None
    assert stub.session_log.rows[-1]['role'] == 'tool'  # the poisoned state

    # step() raised before yielding anything -> empty segment.
    LLMAgent._persist_partial_round(stub, [], 0, marker='errored')

    assert stub.session_log.rows[-1]['role'] == 'assistant'
    assert stub.session_log.rows[-1]['errored'] is True
