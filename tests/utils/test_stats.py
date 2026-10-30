# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import builtins
import errno
import json
import os

import pytest
from ms_agent.utils import atomic_file
from ms_agent.utils.stats import append_stats


def test_appends_history_and_keeps_json_format(tmp_path):
    path = tmp_path / 'nested' / 'workflow_stats.json'
    asyncio.run(append_stats(str(path), {'event': 'first'}))
    asyncio.run(append_stats(str(path), {'event': 'second', 'tag': '中文'}))
    records = json.loads(path.read_text(encoding='utf-8'))
    assert [record['event'] for record in records] == ['first', 'second']
    assert all(record['created_at'] for record in records)
    assert r'\u4e2d' in path.read_text(encoding='utf-8')
    assert list(path.parent.iterdir()) == [path]


def test_serialization_failure_preserves_previous_history(tmp_path):
    path = tmp_path / 'workflow_stats.json'
    original = '[{"event": "previous"}]'
    path.write_text(original, encoding='utf-8')
    with pytest.raises(TypeError):
        asyncio.run(append_stats(str(path), {'event': object()}))
    assert path.read_text(encoding='utf-8') == original
    assert list(tmp_path.iterdir()) == [path]


def test_partial_write_failure_preserves_history_for_next_append(tmp_path,
                                                                monkeypatch):
    path = tmp_path / 'workflow_stats.json'
    original = '[{"event": "previous"}]'
    path.write_text(original, encoding='utf-8')
    real_open = builtins.open
    real_fdopen = os.fdopen

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, text):
            self.stream.write(text[:1])
            self.stream.flush()
            raise OSError(errno.ENOSPC, 'simulated full device')

    def failing_open(file, mode='r', *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        return FailingWriter(stream) if 'w' in mode else stream

    def failing_fdopen(fd, *args, **kwargs):
        return FailingWriter(real_fdopen(fd, *args, **kwargs))

    with monkeypatch.context() as patch:
        patch.setattr(builtins, 'open', failing_open)
        patch.setattr(atomic_file.os, 'fdopen', failing_fdopen)
        with pytest.raises(OSError, match='simulated full device'):
            asyncio.run(append_stats(str(path), {'event': 'interrupted'}))

    assert path.read_text(encoding='utf-8') == original
    assert list(tmp_path.iterdir()) == [path]
    asyncio.run(append_stats(str(path), {'event': 'recovered'}))
    assert [record['event'] for record in json.loads(path.read_text())] == [
        'previous', 'recovered'
    ]


def test_replace_failure_preserves_previous_history(tmp_path, monkeypatch):
    path = tmp_path / 'workflow_stats.json'
    original = '[{"event": "previous"}]'
    path.write_text(original, encoding='utf-8')

    def fail_replace(*args):
        raise OSError('simulated rename failure')

    monkeypatch.setattr(atomic_file.os, 'replace', fail_replace)
    with pytest.raises(OSError, match='simulated rename failure'):
        asyncio.run(append_stats(str(path), {'event': 'next'}))
    assert path.read_text(encoding='utf-8') == original
    assert list(tmp_path.iterdir()) == [path]
