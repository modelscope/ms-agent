# Copyright (c) ModelScope Contributors. All rights reserved.
"""Atomic whole-file writes: no torn content, no lost rename, no leftovers."""
import json
import threading

import pytest
from ms_agent.utils.atomic_file import atomic_write_json, atomic_write_text


def test_replaces_existing_content(tmp_path):
    path = tmp_path / 'a.txt'
    path.write_text('old', encoding='utf-8')
    atomic_write_text(path, 'new')
    assert path.read_text(encoding='utf-8') == 'new'
    assert [p.name for p in tmp_path.iterdir()] == ['a.txt']


def test_creates_missing_parents(tmp_path):
    path = tmp_path / 'deep' / 'nested' / 'a.json'
    atomic_write_json(path, {'a': 1})
    assert json.loads(path.read_text(encoding='utf-8')) == {'a': 1}


def test_fsync_writes_the_same_bytes(tmp_path):
    path = tmp_path / 'durable.json'
    atomic_write_json(path, {'a': 1}, fsync=True)
    assert json.loads(path.read_text(encoding='utf-8')) == {'a': 1}
    assert [p.name for p in tmp_path.iterdir()] == ['durable.json']


def test_a_failed_write_leaves_neither_a_temp_file_nor_damage(tmp_path):
    path = tmp_path / 'a.json'
    atomic_write_json(path, {'good': True})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(path, {'bad': Unserializable()})

    assert json.loads(path.read_text(encoding='utf-8')) == {'good': True}
    assert [p.name for p in tmp_path.iterdir()] == ['a.json']


def test_concurrent_writers_neither_fail_nor_corrupt(tmp_path):
    # Payloads are large so a torn write would span many buffer writes.
    path = tmp_path / 'shared.json'
    writers = 6
    payloads = {i: {'id': f'w{i}', 'pad': str(i) * 100000}
                for i in range(writers)}
    failures: list[BaseException] = []
    reads = 0
    lock = threading.Lock()
    start = threading.Barrier(writers)

    def hammer(i: int) -> None:
        nonlocal reads
        start.wait()
        for _ in range(20):
            try:
                atomic_write_json(path, payloads[i])
                got = json.loads(path.read_text(encoding='utf-8'))
                assert got in payloads.values(), 'mixed content'
                with lock:
                    reads += 1
            except BaseException as exc:  # noqa: B902 - reported verbatim
                failures.append(exc)

    threads = [threading.Thread(target=hammer, args=(i,))
               for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not failures, f'{len(failures)} failed: {failures[:3]}'
    assert reads == writers * 20
    assert [p.name for p in tmp_path.iterdir()] == ['shared.json']
