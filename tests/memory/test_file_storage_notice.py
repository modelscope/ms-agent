"""Memory tool results the user can act on."""
import errno

import pytest

from ms_agent.memory.unified.backends.file_based import FileBasedBackend
from ms_agent.memory.unified.config import MemoryConfig
from ms_agent.memory.unified.storage import file_storage as storage_mod
from ms_agent.memory.unified.user_notice import (
    CHAR_LIMIT_NOTICE,
    DISK_NOTICE,
    MISSING_DIR_NOTICE,
    NO_SPACE_NOTICE,
    PERMISSION_NOTICE,
)


@pytest.mark.asyncio
async def test_char_limit_is_the_tool_result_and_does_not_stick(tmp_path):
    backend = FileBasedBackend(
        MemoryConfig(base_dir=str(tmp_path), char_limit=20))
    over = await backend.handle_tool_call('memory', {
        'action': 'add',
        'content': 'x' * 40,
    })
    assert over == CHAR_LIMIT_NOTICE
    assert not (tmp_path / 'MEMORY.md').exists()

    missed = await backend.handle_tool_call('memory', {
        'action': 'replace',
        'content': 'missing',
        'new_content': 'y',
    })
    assert missed == '更新失败'
    assert CHAR_LIMIT_NOTICE not in missed


@pytest.mark.asyncio
async def test_char_limit_is_logged_as_a_warning(tmp_path, monkeypatch):
    seen = []

    def _warning(msg, *args, **kwargs):
        seen.append(msg % args if args else msg)

    monkeypatch.setattr(storage_mod.logger, 'warning', _warning)
    backend = FileBasedBackend(
        MemoryConfig(base_dir=str(tmp_path), char_limit=20))
    await backend.handle_tool_call('memory', {
        'action': 'add',
        'content': 'x' * 40,
    })
    assert any('char limit' in msg for msg in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize('exc,notice', [
    (FileNotFoundError(errno.ENOENT, 'gone', 'MEMORY.md'), MISSING_DIR_NOTICE),
    (PermissionError(errno.EACCES, 'denied', 'MEMORY.md'), PERMISSION_NOTICE),
    (OSError(errno.ENOSPC, 'full', 'MEMORY.md'), NO_SPACE_NOTICE),
    (OSError(errno.EIO, 'io', 'MEMORY.md'), DISK_NOTICE),
])
async def test_disk_error_sentence_matches_the_cause(tmp_path, monkeypatch,
                                                     exc, notice):

    def boom(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(storage_mod, 'atomic_write_text', boom)
    backend = FileBasedBackend(MemoryConfig(base_dir=str(tmp_path)))
    added = await backend.handle_tool_call('memory', {
        'action': 'add',
        'content': 'remember this',
    })
    assert added == notice

    removed = await backend.handle_tool_call('memory', {
        'action': 'remove',
        'content': 'remember this',
    })
    assert removed == notice
