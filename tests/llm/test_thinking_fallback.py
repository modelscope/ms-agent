# Copyright (c) ModelScope Contributors. All rights reserved.
"""Thinking parameters are dropped and retried when a model refuses them.

Support for "thinking" is per-model and unpredictable from the name — probing
one provider's 122 chat models turned up refusals across vision, OCR, omni,
open-weight and even non-Qwen families — and a refusal is a hard 400, not an
ignored flag. So the client does not try to know: it asks, and on a refusal
retries once with thinking off, remembering the model.
"""
import pytest

from ms_agent.llm import openai_llm as O
from ms_agent.llm import thinking as T
from ms_agent.llm.transport import openai_compat as TC


class _Recorder:
    """Stands in for ``client.chat.completions``; records every call and fails
    the ones that ask for thinking."""

    def __init__(self, refuse: str = 'thinking_budget must be positive'):
        self.calls = []
        self.refuse = refuse

    def create(self, **kwargs):
        self.calls.append(kwargs)
        extra = kwargs.get('extra_body') or {}
        asked = extra.get('enable_thinking') or kwargs.get('enable_thinking')
        if asked and self.refuse:
            raise RuntimeError(f'Error code: 400 - {self.refuse}')
        return f'completion-{len(self.calls)}'


def _client(recorder):
    ns = type('NS', (), {})
    client = ns()
    client.chat = ns()
    client.chat.completions = recorder
    client.base_url = 'https://example.test/v1'
    return client


def _llm(recorder, model='some-model'):
    llm = O.OpenAI.__new__(O.OpenAI)  # bypass __init__ (config/network)
    llm.client = _client(recorder)
    llm.model = model
    llm.args = {}
    llm._format_input_message = lambda m: m
    return llm


@pytest.fixture(autouse=True)
def _clear_memo():
    T.MODELS_REFUSING_THINKING.clear()
    yield
    T.MODELS_REFUSING_THINKING.clear()


def test_refusal_is_retried_with_thinking_explicitly_off():
    rec = _Recorder()
    out = _llm(rec)._call_llm([], None, extra_body={'enable_thinking': True})

    assert out == 'completion-2'  # the retry's result, not an exception
    assert len(rec.calls) == 2
    # Explicitly OFF, not merely absent: some models default it on and then
    # refuse the call ("must be set to false for non-stream call").
    assert rec.calls[1]['extra_body'] == {'enable_thinking': False}


def test_budget_keys_are_dropped_and_other_extras_kept():
    rec = _Recorder()
    _llm(rec)._call_llm([],
                        None,
                        extra_body={
                            'enable_thinking': True,
                            'thinking_budget': 512,
                            'unrelated': 'keep me'
                        })
    retried = rec.calls[1]['extra_body']
    assert retried == {'enable_thinking': False, 'unrelated': 'keep me'}


def test_the_refusal_is_remembered_so_later_turns_cost_one_call():
    rec = _Recorder()
    llm = _llm(rec)
    llm._call_llm([], None, extra_body={'enable_thinking': True})
    assert len(rec.calls) == 2

    llm._call_llm([], None, extra_body={'enable_thinking': True})
    assert len(rec.calls) == 3  # no failed attempt this time
    assert rec.calls[2]['extra_body'] == {'enable_thinking': False}


def test_memo_is_per_model():
    rec = _Recorder()
    _llm(rec, model='refuser')._call_llm([],
                                         None,
                                         extra_body={'enable_thinking': True})
    assert len(rec.calls) == 2
    # A different model on the same endpoint must still get its chance to think.
    _llm(rec, model='thinker')._call_llm([],
                                         None,
                                         extra_body={'enable_thinking': True})
    assert len(rec.calls) == 4
    assert rec.calls[2]['extra_body'] == {'enable_thinking': True}


def test_unrelated_400_is_not_retried():
    rec = _Recorder(refuse='context length exceeded')

    class _Always(_Recorder):

        def create(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError('Error code: 400 - context length exceeded')

    rec = _Always()
    with pytest.raises(RuntimeError, match='context length'):
        _llm(rec)._call_llm([], None, extra_body={'enable_thinking': True})
    assert len(rec.calls) == 1


def test_a_request_without_thinking_is_never_retried():
    """A 400 that merely mentions thinking, on a call that asked for none, is
    somebody else's problem — retrying would hide it."""

    class _Always(_Recorder):

        def create(self, **kwargs):
            self.calls.append(kwargs)
            raise RuntimeError('Error code: 400 - thinking is unsupported')

    rec = _Always()
    with pytest.raises(RuntimeError):
        _llm(rec)._call_llm([], None, temperature=0.5)
    assert len(rec.calls) == 1
    assert not T.MODELS_REFUSING_THINKING


def test_the_router_transport_heals_too():
    """The WebUI does not go through llm/openai_llm.py at all — its provider
    router uses transport/openai_compat.py. A fallback that only covered one of
    them looked fine in unit tests and still failed in the browser."""
    rec = _Recorder()
    tr = TC.OpenAICompatTransport.__new__(TC.OpenAICompatTransport)
    tr.client = _client(rec)
    tr.model = 'refuser'
    tr.args = {}
    tr._format_input_message = lambda m: m

    out = tr._call_llm([], None, extra_body={'enable_thinking': True})
    assert out == 'completion-2'
    assert rec.calls[1]['extra_body'] == {'enable_thinking': False}
