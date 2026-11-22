import json
import threading

import pytest
from ms_agent.project.store import JSONFileStore


class TestJSONFileStore:
    def test_write_and_read(self, tmp_path):
        store = JSONFileStore(tmp_path / 'test.json')
        data = {'name': 'test', 'value': 42}
        store.write(data)
        assert store.read() == data

    def test_exists_false_when_missing(self, tmp_path):
        store = JSONFileStore(tmp_path / 'missing.json')
        assert not store.exists()

    def test_exists_true_after_write(self, tmp_path):
        store = JSONFileStore(tmp_path / 'test.json')
        store.write({'key': 'val'})
        assert store.exists()

    def test_read_empty_when_missing(self, tmp_path):
        store = JSONFileStore(tmp_path / 'missing.json')
        assert store.read() == {}

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        store = JSONFileStore(tmp_path / 'test.json')
        store.write({'a': 1})
        assert not (tmp_path / 'test.tmp').exists()
        # Temp names are unique per writer now, so check for any leftover.
        assert [p.name for p in tmp_path.iterdir()] == ['test.json']
        assert (tmp_path / 'test.json').exists()

    def test_concurrent_writes_neither_fail_nor_corrupt(self, tmp_path):
        store = JSONFileStore(tmp_path / 'project.json')
        writers = 6
        payloads = {i: {'id': f'w{i}', 'pad': str(i) * 100000}
                    for i in range(writers)}
        failures: list[BaseException] = []
        reads: list[str] = []
        start = threading.Barrier(writers)

        def hammer(i: int) -> None:
            start.wait()
            for _ in range(20):
                try:
                    store.write(payloads[i])
                    got = store.read()
                    assert got in payloads.values(), 'mixed content'
                    reads.append(got['id'])
                except BaseException as exc:  # noqa: B902 - reported verbatim
                    failures.append(exc)

        threads = [threading.Thread(target=hammer, args=(i,))
                   for i in range(writers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not failures, f'{len(failures)} failed: {failures[:3]}'
        assert len(reads) == writers * 20
        assert json.loads((tmp_path / 'project.json').read_text(
            encoding='utf-8')) in payloads.values()
        assert sorted(p.name for p in tmp_path.iterdir()) == ['project.json']

    def test_creates_parent_dirs(self, tmp_path):
        store = JSONFileStore(tmp_path / 'nested' / 'deep' / 'test.json')
        store.write({'nested': True})
        assert store.read() == {'nested': True}

    def test_unicode_roundtrip(self, tmp_path):
        store = JSONFileStore(tmp_path / 'unicode.json')
        data = {'name': '翻译项目', 'emoji': '🚀'}
        store.write(data)
        assert store.read() == data
