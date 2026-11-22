"""Probe identity, concurrency and cancellation semantics."""
import asyncio

import pytest
from app.backends.ms_agent import mcp_health as health


@pytest.fixture(autouse=True)
async def clean_probes():
    health.invalidate_cache()
    yield
    await health.shutdown()


async def test_shared_probe_survives_one_cancelled_waiter(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def probe(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return True, None
    monkeypatch.setattr(health, 'check_server', probe)
    a = asyncio.create_task(health.check_server_cached('x', {'url': 'http://x'}))
    b = asyncio.create_task(health.check_server_cached('x', {'url': 'http://x'}))
    await entered.wait()
    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    release.set()
    assert (await b).healthy is True
    assert calls == 1


async def test_late_shallow_cannot_overwrite_deep_and_ttl_starts_at_finish(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    clock = [100.0]
    monkeypatch.setattr(health.time, 'time', lambda: clock[0])

    async def probe(server, timeout, deep=False):
        if deep:
            return False, 'list_tools failed'
        entered.set()
        await release.wait()
        return None, None
    monkeypatch.setattr(health, 'check_server', probe)
    server = {'command': 'python3'}
    shallow = asyncio.create_task(health.check_server_cached('x', server))
    await entered.wait()
    clock[0] = 200.0
    deep = await health.check_server_cached('x', server, deep=True)
    assert deep.expires_at == 210.0
    release.set()
    assert await shallow == deep
    assert await health.check_server_cached('x', server) == deep


async def test_identity_includes_parameters_and_scope(monkeypatch):
    calls = []
    async def probe(*args, **kwargs):
        calls.append(args)
        return True, None
    monkeypatch.setattr(health, 'check_server', probe)
    await health.check_server_cached('x', {'url': 'http://x'})
    variants = {'args': ['a'], 'env': {'TOKEN': 'secret'},
                'headers': {'Authorization': 'secret'}, 'transport': 'sse'}
    for field, value in variants.items():
        await health.check_server_cached('x', {'url': 'http://x', field: value})
    await health.check_server_cached('x', {'url': 'http://x'}, scope='project:p')
    assert len(calls) == 6
    assert 'secret' not in repr(health._cache.keys())


async def test_invalidated_inflight_result_cannot_repopulate_cache(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    async def probe(*args, **kwargs):
        entered.set()
        await release.wait()
        return True, None
    monkeypatch.setattr(health, 'check_server', probe)
    task = asyncio.create_task(health.check_server_cached('x', {'url': 'http://x'}))
    await entered.wait()
    health.invalidate_server('x')
    release.set()
    await task
    assert not health._cache


async def test_diagnostic_redacts_url_headers_and_env(monkeypatch):
    async def failed(server):
        raise ValueError('https://user:password@host/private?key=hidden Bearer abc-token env-secret')
    monkeypatch.setattr(health, '_remote_handshake', failed)
    ok, err = await health.check_server({'url': 'https://host',
        'headers': {'Authorization': 'Bearer abc-token'}, 'env': {'KEY': 'env-secret'}})
    assert ok is False
    assert all(secret not in err for secret in ['password', 'hidden', 'abc-token', 'env-secret'])


@pytest.mark.parametrize('manual_finishes_first', [False, True])
async def test_manual_budget_is_independent_of_automatic_probe(monkeypatch, manual_finishes_first):
    entered = {6: asyncio.Event(), 45: asyncio.Event()}
    release = {6: asyncio.Event(), 45: asyncio.Event()}
    calls = []

    async def probe(server, timeout, deep=False):
        calls.append(timeout)
        entered[timeout].set()
        await release[timeout].wait()
        return (True, None) if timeout == 45 else (False, 'timed out')

    monkeypatch.setattr(health, 'check_server', probe)
    server = {'url': 'http://fixture.invalid'}
    automatic = asyncio.create_task(health.check_server_cached('x', server))
    await entered[6].wait()
    manual = asyncio.create_task(health.check_server_cached(
        'x', server, timeout=45, deep=True, refresh=True))
    try:
        await asyncio.wait_for(entered[45].wait(), .5)
        if manual_finishes_first:
            release[45].set()
            assert (await manual).healthy is True
            release[6].set()
            assert (await automatic).healthy is True
        else:
            release[6].set()
            assert (await automatic).healthy is False
            release[45].set()
            assert (await manual).healthy is True
        assert calls == [6, 45]
        assert (await health.check_server_cached('x', server)).healthy is True
    finally:
        release[6].set()
        release[45].set()
        await asyncio.gather(automatic, manual, return_exceptions=True)


async def test_short_cached_failure_does_not_satisfy_longer_request(monkeypatch):
    calls = []
    async def probe(server, timeout, deep=False):
        calls.append(timeout)
        return (timeout > 6, None)
    monkeypatch.setattr(health, 'check_server', probe)
    server = {'url': 'http://fixture.invalid'}
    assert (await health.check_server_cached('x', server)).healthy is False
    assert (await health.check_server_cached('x', server, timeout=45, deep=True)).healthy is True
    assert calls == [6, 45]


@pytest.mark.parametrize('bad_env', [7, [], 'config-test-secret'])
async def test_health_api_keeps_valid_rows_with_invalid_config(tmp_path, monkeypatch, bad_env):
    import sys
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from ms_agent.config import MCPConfigManager
    from app.api.mcps import router
    from app.backends.ms_agent import mcps
    from app.core.envelope import register_exception_handlers

    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    manager = MCPConfigManager(global_root=str(tmp_path))
    manager.add('valid', {'command': sys.executable}, scope='global')
    invalid = {'command': sys.executable, 'env': bad_env}
    manager.add('invalid', invalid, scope='global')
    # Both the uncached entry point and public API must isolate bad config.
    assert (await health.check_server(invalid, deep=True))[0] is False
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url='http://fixture.invalid') as http:
        response = await http.get('/api/mcps/health')
        assert response.status_code == 200
        rows = {row['name']: row for row in response.json()['data']}
        assert rows['valid']['healthy'] is None
        assert rows['invalid']['healthy'] is False
        assert rows['invalid']['error']
        single = await http.get(f"/api/mcps/{mcps._encode_id('global', 'invalid')}/health")
        assert single.status_code == 200
        assert single.json()['data']['healthy'] is False
        assert 'config-test-secret' not in response.text + single.text


async def test_matching_effective_budgets_share_one_probe(monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def probe(server, timeout, deep=False):
        calls.append(timeout)
        entered.set()
        await release.wait()
        return True, None

    monkeypatch.setattr(health, 'check_server', probe)
    server = {'url': 'http://fixture.invalid', 'startup_timeout': 5}
    automatic = asyncio.create_task(health.check_server_cached('x', server))
    await entered.wait()
    manual = asyncio.create_task(health.check_server_cached(
        'x', server, timeout=45, deep=True, refresh=True))
    await asyncio.sleep(0)
    release.set()
    assert all(result.healthy for result in await asyncio.gather(automatic, manual))
    assert calls == [5]


async def test_shutdown_closes_different_budget_probes(monkeypatch):
    entered = {6: asyncio.Event(), 45: asyncio.Event()}
    closed = set()

    async def probe(server, timeout, deep=False):
        entered[timeout].set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.add(timeout)

    monkeypatch.setattr(health, 'check_server', probe)
    server = {'url': 'http://fixture.invalid'}
    waiters = [asyncio.create_task(health.check_server_cached(
        'x', server, timeout=budget, refresh=True)) for budget in (6, 45)]
    await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), .5)
    await health.shutdown()
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)
    assert closed == {6, 45}
    assert not health._inflight and not health._cache


async def test_explicit_refresh_can_replace_previous_success(monkeypatch):
    answers = iter([(True, None), (False, 'connection closed')])
    async def probe(*args, **kwargs):
        return next(answers)
    monkeypatch.setattr(health, 'check_server', probe)
    server = {'url': 'http://fixture.invalid'}
    assert (await health.check_server_cached('x', server)).healthy is True
    fresh = await health.check_server_cached('x', server, deep=True, timeout=45, refresh=True)
    assert fresh.healthy is False
    assert await health.check_server_cached('x', server) == fresh


@pytest.mark.parametrize('budget', [0, True, float('nan'), 'budget-test-secret'])
async def test_invalid_budget_is_isolated_and_not_exposed(budget):
    server = {'url': 'http://fixture.invalid', 'startup_timeout': budget}
    ok, error = await health.check_server(server)
    assert ok is False and error and 'budget-test-secret' not in error
    result = await health.check_server_cached('x', server)
    assert result.healthy is False and 'budget-test-secret' not in result.error
    assert not health._inflight
