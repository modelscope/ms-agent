"""Selections are persisted per conversation, independent of the next-chat default."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from app.backends.errors import BadRequest, NotFound
from app.backends.ms_agent import agent_settings, common, model_link, session_models, sessions, sidecar
from app.backends.ms_agent.mapping import encode_model_id
from app.schemas.agent_settings import AgentSettings
from app.schemas.session import SessionCreate
from ms_agent.config.model_settings import ModelSettingsManager


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path))
    common.pm().initialize()
    manager = ModelSettingsManager(tmp_path)
    manager.add_provider('first', protocol='openai', api_key='first-test-key',
                         base_url='https://first.invalid/v1', models=['M1', 'M2'])
    manager.add_provider('second', protocol='anthropic', api_key='second-test-key',
                         base_url='https://second.invalid', models=['M3'])
    model_link.set_active_model('first', 'M1')
    return tmp_path, common.pm().get_default_project()


def _new():
    return sessions.create_session(SessionCreate(title='New'))


def _choice(sid):
    return sessions.get_session(sid).model_id


def test_full_session_default_sequence_and_restart(state):
    path, project = state
    m1, m2, m3 = (encode_model_id('first', 'M1'), encode_model_id('first', 'M2'), encode_model_id('second', 'M3'))
    a = _new()
    assert a.model_id == m1
    sessions.update_session_model(a.id, m2)
    b = _new()
    assert b.model_id == m2
    sessions.update_session_model(b.id, m3)
    before = (path / 'settings.json').read_bytes()
    assert _choice(a.id) == m2
    assert _choice(b.id) == m3
    assert (path / 'settings.json').read_bytes() == before
    assert _new().model_id == m3
    from app.backends.ms_agent.bootstrap import bootstrap
    bootstrap()
    assert _choice(a.id) == m2 and _choice(b.id) == m3
    assert model_link.active_model() == ('second', 'M3')
    # Selection changes persist even without sending a message.
    record = common.sm_for(project).get(a.id)
    assert (record.model_provider, record.model) == ('first', 'M2')


def test_draft_first_send_keeps_displayed_model_without_changing_default(state):
    from app.backends.ms_agent.chat import _resolve_or_create
    from app.schemas.chat import ChatRequest
    old = encode_model_id('first', 'M1')
    model_link.set_active_model('second', 'M3')
    _, session = _resolve_or_create(ChatRequest(model_id=old))
    assert (session.model_provider, session.model) == ('first', 'M1')
    assert model_link.active_model() == ('second', 'M3')
    # An existing session ignores request-provided model overrides.
    _, same = _resolve_or_create(ChatRequest(session_id=session.id, model_id=encode_model_id('second', 'M3')))
    assert same.model == 'M1'


def test_missing_session_is_not_recreated(state):
    from app.backends.ms_agent.chat import _resolve_or_create
    from app.schemas.chat import ChatRequest
    with pytest.raises(NotFound):
        _resolve_or_create(ChatRequest(session_id='deleted'))
    assert sessions.list_sessions() == []


def test_model_snapshot_is_pinned_and_credentials_are_matched(state):
    _, project = state
    a = _new()
    model_link.set_active_model('second', 'M3')
    session = common.sm_for(project).get(a.id)
    _, first = session_models.prepare(project, session)
    assert first.key == ('first', 'M1')
    assert first.settings['llm']['api_key'] == 'first-test-key'
    assert first.settings['llm']['protocol'] == 'openai'
    session_models.change(project, a.id, encode_model_id('second', 'M3'))
    _, second = session_models.prepare(project, session)
    assert first.key == ('first', 'M1')
    assert first.settings['llm']['api_key'] == 'first-test-key'
    assert second.settings['llm']['api_key'] == 'second-test-key'
    assert second.settings['llm']['protocol'] == 'anthropic'


def test_build_agent_uses_pinned_model_for_transport_and_generation(state):
    from app.backends.ms_agent.config import build_agent
    from ms_agent.ui.events import RecordingSink
    _, project = state
    sidecar.merge('providers', 'first', {'default_generation_params': {'temperature': 0.4}})
    sidecar.merge('models', encode_model_id('first', 'M1'), {'advanced_params': {'max_tokens': 101}, 'supports_vision': True})
    session = common.sm_for(project).get(_new().id)
    session, snapshot = session_models.prepare(project, session)
    model_link.set_active_model('second', 'M3')
    sidecar.merge('providers', 'first', {'default_generation_params': {'temperature': 0.9}})
    agent = build_agent(project, session, event_sink=RecordingSink(), input_source=None,
                        mcp_config={}, model_snapshot=snapshot)
    cfg = agent.config
    assert cfg.llm.service == 'first' and cfg.llm.model == 'M1'
    assert cfg.llm.first_api_key == 'first-test-key'
    assert cfg.llm.first_base_url == 'https://first.invalid/v1'
    assert cfg.llm.protocol == 'openai'
    assert cfg.llm.supports_vision is True
    assert cfg.generation_config.temperature == 0.4 and cfg.generation_config.max_tokens == 101
    assert 'second_api_key' not in cfg.llm


def test_default_change_does_not_invalidate_bound_session(state):
    from app.backends.ms_agent.runtime import _settings_fingerprint
    path, project = state
    session = common.sm_for(project).get(_new().id)
    _, before = session_models.prepare(project, session)
    fingerprint = _settings_fingerprint(project, before)
    model_link.set_active_model('second', 'M3')
    _, after = session_models.prepare(project, session)
    assert _settings_fingerprint(project, after) == fingerprint
    ModelSettingsManager(path).add_provider('first', api_key='new-test-key')
    _, updated = session_models.prepare(project, session)
    assert updated.settings['llm']['api_key'] == 'new-test-key'
    assert _settings_fingerprint(project, updated) != fingerprint


@pytest.mark.parametrize('kind,expected', [
    ('sidecar', ('first', 'M2')),
    ('bare', ('first', 'M1')),
    ('unknown', (None, None)),
    ('ambiguous', (None, 'M1')),
])
def test_legacy_selection_migration_preserves_identity_and_timestamps(state, kind, expected):
    path, project = state
    manager = common.sm_for(project)
    old = manager.create(model='M1' if kind in ('bare', 'ambiguous') else None)
    if kind == 'sidecar':
        sidecar.merge('sessions', old.id, {'model_id': encode_model_id('first', 'M2')})
    if kind == 'ambiguous':
        ModelSettingsManager(path).add_model('second', 'M1')
    before = (path / 'settings.json').read_bytes()
    migrated = session_models.migrate(project, old)
    assert (migrated.model_provider, migrated.model) == expected
    assert (migrated.created_at, migrated.updated_at) == (old.created_at, old.updated_at)
    saved = manager.get(old.id)
    assert (saved.model_provider, saved.model) == expected
    assert (path / 'settings.json').read_bytes() == before
    if kind in ('unknown', 'ambiguous'):
        with pytest.raises(BadRequest, match='No model is recorded'):
            session_models.prepare(project, old)


@pytest.mark.parametrize('change', ['delete_model', 'delete_provider', 'disable', 'clear_key'])
def test_unavailable_selection_never_falls_back(state, change):
    path, project = state
    session = common.sm_for(project).get(_new().id)
    manager = ModelSettingsManager(path)
    if change == 'delete_model':
        manager.remove_model('first', 'M1')
    elif change == 'delete_provider':
        manager.remove_provider('first')
    elif change == 'disable':
        sidecar.merge('providers', 'first', {'enabled': False})
    else:
        manager.add_provider('first', api_key='')
    model_link.set_active_model('second', 'M3')
    with pytest.raises(BadRequest):
        session_models.prepare(project, session)
    assert common.sm_for(project).get(session.id).model == 'M1'


def test_old_llm_credentials_survive_default_switch_without_reviving_cleared_key(state):
    path, project = state
    data = model_link._load()
    data['providers']['first'].pop('api_key')
    data['llm']['api_key'] = 'legacy-test-key'
    model_link._save(data)
    session = common.sm_for(project).get(_new().id)
    model_link.set_active_model('second', 'M3')
    assert session_models.prepare(project, session)[1].settings['llm']['api_key'] == 'legacy-test-key'
    ModelSettingsManager(path).add_provider('first', api_key='')
    with pytest.raises(BadRequest):
        session_models.prepare(project, session)


def test_model_switch_preserves_memory_and_explicit_clear_is_local(state):
    agent_settings.update_settings(AgentSettings(default_memory_enabled=True))
    result = agent_settings.update_settings(AgentSettings(default_model_id=encode_model_id('first', 'M2')))
    assert result.default_memory_enabled is True
    agent_settings.update_settings(AgentSettings(memory_llm_model='one', memory_embed_model='embed'))
    agent_settings.update_settings(AgentSettings(memory_llm_model=None))
    result = agent_settings.get_settings()
    assert result.memory_llm_model is None and result.memory_embed_model == 'embed'


def test_concurrent_sessions_and_configuration_changes(state):
    path, _ = state
    all_sessions = [_new() for _ in range(4)]
    start = Barrier(len(all_sessions), timeout=5)

    def save(index):
        start.wait()
        mid = encode_model_id('first', 'M2') if index % 2 else encode_model_id('second', 'M3')
        sessions.update_session_model(all_sessions[index].id, mid)
        ModelSettingsManager(path).add_model('first', f'extra-{index}')
        agent_settings.update_settings(AgentSettings(default_memory_enabled=True))
        return mid
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(save, range(len(all_sessions))))
    assert [_choice(s.id) for s in all_sessions] == ids
    assert agent_settings.get_settings().default_memory_enabled is True
    assert {f'extra-{i}' for i in range(len(all_sessions))} <= set(ModelSettingsManager(path).list_custom_providers()['first']['models'])


def test_invalid_selection_leaves_session_and_default_unchanged(state):
    path, _ = state
    session = _new()
    before = (path / 'settings.json').read_bytes()
    with pytest.raises(BadRequest):
        sessions.update_session_model(session.id, encode_model_id('missing', 'model'))
    assert _choice(session.id) == session.model_id
    assert (path / 'settings.json').read_bytes() == before


def test_default_write_failure_is_reported_and_partial_save_remains_readable(state, monkeypatch):
    path, _ = state
    session = _new()
    before = (path / 'settings.json').read_bytes()

    def fail(_):
        raise OSError('injected write failure')

    monkeypatch.setattr(model_link, '_save_unlocked', fail)
    with pytest.raises(OSError):
        sessions.update_session_model(session.id, encode_model_id('second', 'M3'))
    assert (path / 'settings.json').read_bytes() == before
    # Reads reveal a partial save instead of claiming both writes were committed.
    assert _choice(session.id) == encode_model_id('second', 'M3')


@pytest.mark.parametrize('action', ['rename', 'delete'])
async def test_late_generated_title_does_not_overwrite_rename_or_recreate(state, monkeypatch, action):
    from app.backends.ms_agent import chat
    _, project = state
    manager = common.sm_for(project)
    session = manager.create()
    entered, finish = asyncio.Event(), asyncio.Event()

    async def title(_):
        entered.set()
        await finish.wait()
        return 'Generated title', 'coding'
    monkeypatch.setattr(chat.titler, 'generate_title_and_category', title)
    task = asyncio.create_task(chat._apply_title(project, session.id, 'hello'))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        if action == 'delete':
            manager.delete(session.id)
        else:
            manager.update(session.id, name='User title')
        finish.set()
        assert await asyncio.wait_for(task, timeout=5) is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    saved = manager.get(session.id)
    if action == 'delete':
        assert saved is None
        assert sidecar.get('sessions', session.id) is None
    else:
        assert saved.name == 'User title'


def test_deleted_default_model_does_not_return_on_restart(state):
    path, _ = state
    ModelSettingsManager(path).remove_model('first', 'M1')
    from app.backends.ms_agent.bootstrap import bootstrap
    bootstrap()
    assert 'M1' not in ModelSettingsManager(path).list_custom_providers()['first']['models']
    assert agent_settings.get_settings().default_model_id is None


@pytest.mark.parametrize('kind', ['model', 'provider'])
def test_metadata_update_and_delete_are_one_serialized_operation(state, monkeypatch, kind):
    from concurrent.futures import TimeoutError
    from app.backends.ms_agent import models, providers
    from app.schemas.model import ModelUpdate
    from app.schemas.provider import ProviderUpdate
    entered, release, deleting = Event(), Event(), Event()
    merge = sidecar.merge

    def paused_merge(*args, **kwargs):
        entered.set()
        assert release.wait(10), 'metadata update was never released'
        return merge(*args, **kwargs)

    monkeypatch.setattr(sidecar, 'merge', paused_merge)
    mid = encode_model_id('first', 'M1')
    if kind == 'model':
        update = lambda: models.update_model(mid, ModelUpdate(display_name='new name'))
        delete = lambda: models.delete_model(mid)
        section, key = 'models', mid
    else:
        update = lambda: providers.update_provider('first', ProviderUpdate(enabled=False))
        delete = lambda: providers.delete_provider('first')
        section, key = 'providers', 'first'

    def remove():
        deleting.set()
        delete()

    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(update)
        try:
            assert entered.wait(5)
            removed = pool.submit(remove)
            assert deleting.wait(5)
            with pytest.raises(TimeoutError):
                removed.result(timeout=0.05)
        finally:
            release.set()
        updating.result(timeout=5)
        removed.result(timeout=5)
    assert sidecar.get(section, key) is None
