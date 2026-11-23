# Copyright (c) ModelScope Contributors. All rights reserved.
"""Regression tests for the ``text_hash`` ``keep_n_chars`` contract.

The docstring defines ``keep_n_chars`` as "The number of characters to keep
from the end of the hash". Keeping zero (or fewer) characters must yield an
empty string; a zero/negative slice index would otherwise silently return
most of the digest.
"""
import hashlib

from ms_agent.utils.utils import text_hash


def test_zero_keep_n_chars_returns_empty():
    assert text_hash('x', 0) == ''


def test_negative_keep_n_chars_returns_empty():
    assert text_hash('x', -1) == ''


def test_positive_keep_n_chars_truncates_to_requested_length():
    result = text_hash('x', 4)
    assert len(result) == 4
    assert result == hashlib.sha256(b'x').hexdigest()[-4:]


def test_default_keep_n_chars_returns_eight_characters():
    result = text_hash('x')
    assert len(result) == 8
    assert result == hashlib.sha256(b'x').hexdigest()[-8:]
