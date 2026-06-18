import json
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
        assert (tmp_path / 'test.json').exists()

    def test_creates_parent_dirs(self, tmp_path):
        store = JSONFileStore(tmp_path / 'nested' / 'deep' / 'test.json')
        store.write({'nested': True})
        assert store.read() == {'nested': True}

    def test_unicode_roundtrip(self, tmp_path):
        store = JSONFileStore(tmp_path / 'unicode.json')
        data = {'name': '翻译项目', 'emoji': '🚀'}
        store.write(data)
        assert store.read() == data
