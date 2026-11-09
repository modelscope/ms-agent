"""Catalog refresh contracts: no provider credentials or public network."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from ms_agent.llm import catalog_update as service, model_catalog as catalog


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    monkeypatch.setenv('MS_AGENT_MODEL_CATALOG', 'local')
    monkeypatch.setattr(catalog, '_cache', catalog._UNSET)
    # Keep validator coverage but avoid processing the full catalog each case.
    provider = catalog.validate_bundle()[0]['deepseek']
    return json.dumps({'deepseek': provider}, ensure_ascii=False).encode()


def test_refresh_is_atomic_pinned_and_selects_freshest(isolated, monkeypatch):
    active = catalog.catalog_info()
    monkeypatch.setattr(service, 'download', AsyncMock(return_value=isolated))
    assert asyncio.run(service.update(force=True))['result'] == 'updated'
    assert catalog.catalog_info() == active
    state = service.status()
    assert state['pending']['revision'] != active['revision']
    previous = (service.cache_dir() / 'current').read_bytes()
    monkeypatch.setattr(service, 'download', AsyncMock(return_value=b'{}'))
    assert asyncio.run(service.update(force=True))['result'] == 'failed'
    assert (service.cache_dir() / 'current').read_bytes() == previous
    monkeypatch.setattr(catalog, '_cache', catalog._UNSET)
    assert catalog.catalog_info()['location'] == 'cache'
    assert catalog.catalog_info()['revision'] == state['pending']['revision']
    bundled = catalog.validate_bundle()
    future = (bundled[0], dict(bundled[1], fetched_at='2099-01-01T00:00:00Z'))
    assert service.choose_bundle(future)[1]['location'] == 'bundled'
    (service.cache_dir() / previous.decode().strip() / catalog.SNAPSHOT).write_text('{}')
    assert service.choose_bundle(bundled)[1]['location'] == 'bundled'


def test_cancel_and_concurrent_refresh_leave_old_pointer(isolated, monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def download(timeout):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(service, 'download', download)
        task = asyncio.create_task(service.update(force=True))
        await entered.wait()
        assert (await service.update(force=True))['result'] == 'busy'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not (service.cache_dir() / 'current').exists()
        assert not service._UPDATE_LOCK.locked()
    asyncio.run(run())


def test_publish_failure_and_policy_keep_local_fallback(isolated, monkeypatch):
    from ms_agent.utils import atomic_file
    original = atomic_file.atomic_write_text
    def fail_pointer(path, *args, **kwargs):
        if path.name == 'current':
            raise OSError('write interrupted')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(atomic_file, 'atomic_write_text', fail_pointer)
    downloader = AsyncMock(return_value=isolated)
    monkeypatch.setattr(service, 'download', downloader)
    assert asyncio.run(service.update(force=True))['result'] == 'failed'
    assert service.cached_bundle() is None
    assert catalog.catalog_info()['available']
    downloader.reset_mock()
    assert asyncio.run(service.update())['result'] == 'cached'
    assert asyncio.run(service.prepare_startup())['result'] == 'local'
    monkeypatch.setenv('MS_AGENT_MODEL_CATALOG', 'bundled')
    assert asyncio.run(service.update(force=True))['result'] == 'disabled'
    downloader.assert_not_called()
