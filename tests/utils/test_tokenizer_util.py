"""Regression tests for the ``count_tokens`` return-shape contract.

The docstring promises a list of counts, one per input text, and a lone
integer only when the caller passes a single string. A one-element list must
therefore stay a list rather than collapsing to a scalar.
"""
from ms_agent.utils.tokenizer_util import TokenizerUtil


class _FakeTokenizer:
    """Deterministic stand-in: one token per whitespace-separated word."""

    def encode(self, text):
        return text.split()


def _util():
    util = TokenizerUtil.__new__(TokenizerUtil)
    util.tokenizer = _FakeTokenizer()
    return util


def test_count_tokens_single_string_returns_int():
    result = _util().count_tokens('a')
    assert isinstance(result, int)
    assert result == 1


def test_count_tokens_single_element_list_returns_list():
    result = _util().count_tokens(['a'])
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], int)
    assert result[0] == 1


def test_count_tokens_multi_element_list_returns_list():
    result = _util().count_tokens(['a', 'b c'])
    assert isinstance(result, list)
    assert result == [1, 2]
