"""Context-restore boundary: the legacy tool-call placeholder from OLD session
logs must not re-enter the model context (new logs no longer write it)."""
from ms_agent.session.context_assembler import (_LEGACY_TOOLCALL_PLACEHOLDER,
                                                 _dicts_to_messages)


def test_legacy_toolcall_placeholder_blanked_on_restore():
    # A pre-fix log: assistant with tool_calls AND the synthetic placeholder.
    rows = [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': _LEGACY_TOOLCALL_PLACEHOLDER,
         'tool_calls': [{'id': 'c1', 'tool_name': 't', 'arguments': '{}'}]},
        {'role': 'tool', 'content': 'r', 'tool_call_id': 'c1', 'name': 't'},
    ]
    msgs = _dicts_to_messages(rows)
    asst = [m for m in msgs if m.role == 'assistant'][-1]
    assert asst.content == ''       # placeholder stripped → canonical empty turn
    assert asst.tool_calls          # the tool call itself is preserved


def test_genuine_reply_equal_to_placeholder_without_toolcalls_kept():
    # The same literal but with NO tool_calls is a real assistant reply — the
    # narrow guard (tool_calls required) must leave it untouched.
    rows = [{'role': 'assistant', 'content': _LEGACY_TOOLCALL_PLACEHOLDER}]
    msgs = _dicts_to_messages(rows)
    assert msgs[0].content == _LEGACY_TOOLCALL_PLACEHOLDER


def test_normal_content_untouched():
    rows = [
        {'role': 'assistant', 'content': '让我查一下',
         'tool_calls': [{'id': 'c1', 'tool_name': 't', 'arguments': '{}'}]},
    ]
    msgs = _dicts_to_messages(rows)
    assert msgs[0].content == '让我查一下'
