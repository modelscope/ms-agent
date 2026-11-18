# Copyright (c) ModelScope Contributors. All rights reserved.
"""Both sources of the file backend's prompt must reflect disk changes."""
import asyncio
import json
import os

import pytest

from ms_agent.memory.unified.backends.file_based import FileBasedBackend
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.protocols import MemoryEntry
from ms_agent.memory.unified.storage.facts_storage import FactsStorage


def _save(storage, content):
    asyncio.run(storage.save([MemoryEntry(content=content, confidence=1.0)]))


@pytest.mark.parametrize('strategy', ['fts', 'hybrid'])
@pytest.mark.parametrize('change', ['replace', 'clear', 'delete'])
def test_inject_reflects_changed_facts(tmp_path, strategy, change):
    config = MemoryConfig(base_dir=str(tmp_path), retrieval_strategy=strategy,
                          auto_retrieve=False)
    writer = FactsStorage(config)
    _save(writer, 'Use Python')
    backend = FileBasedBackend(config)
    messages = [{'role': 'system', 'content': 'System'},
                {'role': 'user', 'content': 'Hello'}]
    first = asyncio.run(backend.inject(messages))
    assert 'Use Python' in first[0]['content']

    if change == 'delete':
        writer.facts_path.unlink()
    else:
        asyncio.run(writer.clear())
        if change == 'replace':
            _save(writer, 'Use JavaScript')

    second = asyncio.run(backend.inject(first))
    assert 'Use Python' not in second[0]['content']
    if change == 'replace':
        assert 'Use JavaScript' in second[0]['content']
        assert second[0]['content'].count('<long-term-memory>') == 1
    else:
        assert second[0]['content'] == 'System'


def test_facts_created_after_initial_missing_read(tmp_path):
    config = MemoryConfig(base_dir=str(tmp_path))
    reader = FactsStorage(config)
    assert asyncio.run(reader.list_all()) == []
    _save(FactsStorage(config), 'Created later')
    assert reader.format_for_prompt() == '- [knowledge] Created later'


def test_save_preserves_external_changes(tmp_path):
    config = MemoryConfig(base_dir=str(tmp_path))
    first = FactsStorage(config)
    _save(first, 'Original')
    second = FactsStorage(config)
    _save(second, 'External addition')
    _save(first, 'Later addition')
    persisted = json.loads(first.facts_path.read_text(encoding='utf-8'))
    assert {fact['content'] for fact in persisted['facts']} == {
        'Original', 'External addition', 'Later addition'}


def test_invalidate_forces_facts_reload_with_same_stat(tmp_path):
    config = MemoryConfig(base_dir=str(tmp_path), retrieval_strategy='hybrid',
                          auto_retrieve=False)
    writer = FactsStorage(config)
    _save(writer, 'Old fact')
    backend = FileBasedBackend(config)
    assert 'Old fact' in backend._get_or_build_snapshot()
    path = writer.facts_path
    stat = path.stat()
    path.write_text(path.read_text(encoding='utf-8').replace('Old fact', 'New fact'),
                    encoding='utf-8')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    backend.invalidate()
    assert 'New fact' in backend._get_or_build_snapshot()
    assert 'Old fact' not in backend._get_or_build_snapshot()


def test_unchanged_facts_reuse_cache(tmp_path, monkeypatch):
    storage = FactsStorage(MemoryConfig(base_dir=str(tmp_path)))
    _save(storage, 'Stable fact')
    assert 'Stable fact' in storage.format_for_prompt()

    def unexpected_read(*args, **kwargs):
        pytest.fail('Unchanged facts should use the cached data')

    monkeypatch.setattr(type(storage.facts_path), 'read_text', unexpected_read)
    assert 'Stable fact' in storage.format_for_prompt()


@pytest.mark.parametrize('change', ['delete', 'invalid_json'])
def test_facts_recover_after_unavailable_file(tmp_path, change):
    config = MemoryConfig(base_dir=str(tmp_path))
    reader = FactsStorage(config)
    _save(reader, 'Original fact')
    if change == 'delete':
        reader.facts_path.unlink()
    else:
        reader.facts_path.write_text('{', encoding='utf-8')
    assert asyncio.run(reader.list_all()) == []

    writer = FactsStorage(config)
    asyncio.run(writer.clear())
    _save(writer, 'Restored fact')
    assert reader.format_for_prompt() == '- [knowledge] Restored fact'


def test_external_edit_with_same_size_reloads(tmp_path):
    storage = FactsStorage(MemoryConfig(base_dir=str(tmp_path)))
    _save(storage, 'Old fact')
    path = storage.facts_path
    stat = path.stat()
    path.write_text(path.read_text(encoding='utf-8').replace('Old fact', 'New fact'),
                    encoding='utf-8')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert storage.format_for_prompt() == '- [knowledge] New fact'
