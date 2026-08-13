# Copyright (c) ModelScope Contributors. All rights reserved.
"""External edits to MEMORY.md (WebUI memory editor, hand edits) must reach a
running session: the snapshot in the system prompt rebuilds when the file
changes on disk, not only after the agent's own memory-tool writes."""
import asyncio
import os

from ms_agent.memory.unified.backends.file_based import FileBasedBackend
from ms_agent.memory.unified.config import MemoryConfig


def _backend(tmp_path):
    cfg = MemoryConfig(
        enabled=True,
        storage_backend='file',
        base_dir=str(tmp_path),
        user_id='u1',
        agent_id='a1',
    )
    return FileBasedBackend(cfg)


def _memory_path(backend):
    return backend._file_storage.memory_path


def _bump_mtime(path):
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def test_snapshot_reflects_external_edit(tmp_path):
    backend = _backend(tmp_path)
    path = _memory_path(backend)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('规则A：发布前跑 make check。\n', encoding='utf-8')

    first = backend._get_or_build_snapshot()
    assert '规则A' in first

    # Cached path: unchanged file -> identical snapshot object semantics.
    assert backend._get_or_build_snapshot() == first

    # External edit (editor/UI) -> next build sees it without any dirty flag.
    path.write_text(
        '规则A：发布前跑 make check。\n临时约定：本周试验固定 seed=42。\n',
        encoding='utf-8')
    _bump_mtime(path)
    second = backend._get_or_build_snapshot()
    assert 'seed=42' in second


def test_snapshot_reflects_external_delete(tmp_path):
    backend = _backend(tmp_path)
    path = _memory_path(backend)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('规则A\n', encoding='utf-8')
    assert '规则A' in backend._get_or_build_snapshot()

    path.unlink()
    assert backend._get_or_build_snapshot() == ''


def test_inject_carries_external_edit(tmp_path):
    """End-to-end through inject(): the system message shows the fresh file."""
    backend = _backend(tmp_path)
    path = _memory_path(backend)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('旧内容\n', encoding='utf-8')
    msgs = [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': 'q'}]
    out = asyncio.run(backend.inject([dict(m) for m in msgs]))
    assert '旧内容' in out[0]['content']

    path.write_text('新内容\n', encoding='utf-8')
    _bump_mtime(path)
    out2 = asyncio.run(backend.inject([dict(m) for m in msgs]))
    assert '新内容' in out2[0]['content']
    assert '旧内容' not in out2[0]['content']


def test_inject_replaces_stale_block_instead_of_skipping(tmp_path):
    """A block left on the head by an earlier round must be replaced, not kept:
    otherwise the memory section freezes at its first value for the whole
    session whenever the head is not rebuilt in between."""
    backend = _backend(tmp_path)
    path = _memory_path(backend)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('第一版\n', encoding='utf-8')

    msgs = [{'role': 'system', 'content': 'S'}, {'role': 'user', 'content': 'q'}]
    out = asyncio.run(backend.inject([dict(m) for m in msgs]))
    assert '第一版' in out[0]['content']

    # Same message objects carried into the next round (no head rebuild).
    path.write_text('第二版\n', encoding='utf-8')
    _bump_mtime(path)
    out2 = asyncio.run(backend.inject(out))
    content = out2[0]['content']
    assert '第二版' in content
    assert '第一版' not in content
    assert content.count('<long-term-memory>') == 1
    assert content.startswith('S')
