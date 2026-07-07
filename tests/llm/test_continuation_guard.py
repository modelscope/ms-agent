# Copyright (c) ModelScope Contributors. All rights reserved.
"""PR#920 review #2/#3: continuation (partial/prefix) must only be attempted
when the provider supports it (``continue_gen_mode`` set). Otherwise a truncated
response (``finish_reason='length'``) on a strict OpenAI-compatible API would
send ``partial``/``prefix`` fields + consecutive assistant messages -> 400."""
from unittest.mock import MagicMock, patch

from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.utils import Message


def _transport(continue_gen_mode):
    # Bypass __init__ so no openai client / network is created.
    t = OpenAICompatTransport.__new__(OpenAICompatTransport)
    t.continue_gen_mode = continue_gen_mode
    t._continue_flag = 'prefix' if continue_gen_mode == 'prefix' else 'partial'
    return t


def _length_completion():
    c = MagicMock()
    c.choices[0].finish_reason = 'length'  # truncated
    return c


def test_no_continuation_when_mode_none():
    """continue_gen_mode=None (standard OpenAI/Gemini) -> never continue."""
    t = _transport(None)
    msgs = [Message(role='user', content='hi')]
    with patch.object(t, '_format_output_message',
                      return_value=Message(role='assistant', content='x')), \
            patch.object(t, '_call_llm_for_continue_gen') as cont:
        t._continue_generate(msgs, _length_completion(), tools=None)
    cont.assert_not_called()


def test_continuation_when_mode_set():
    """A provider that supports continuation still continues on 'length'."""
    t = _transport('partial')
    msgs = [Message(role='user', content='hi')]
    stop = MagicMock()
    stop.choices[0].finish_reason = 'stop'  # ends the recursion
    with patch.object(t, '_format_output_message',
                      return_value=Message(role='assistant', content='x')), \
            patch.object(
                t, '_call_llm_for_continue_gen', return_value=stop) as cont:
        t._continue_generate(msgs, _length_completion(), tools=None)
    cont.assert_called_once()
