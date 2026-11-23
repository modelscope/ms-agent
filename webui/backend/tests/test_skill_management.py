"""Public API lifecycle against real files and controlled upstream snapshots."""
import asyncio
import shutil
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.backends.ms_agent import skill_management as management
from app.core.settings import settings
from ms_agent.skill.management import ManagedSource, SkillManagementError, SkillUseLease
from ms_agent.skill.management.models import SourceCollection


class Source:

    def __init__(self, root):
        self.root, self.revision, self.fail = root, 'a' * 40, False

    async def resolve(self, value):
        return ManagedSource(
            'github',
            'fixture/skills',
            'main',
            self.revision,
            url='https://github.com/fixture/skills')

    async def latest(self, source):
        if self.fail:
            raise SkillManagementError('SOURCE_UNAVAILABLE', 'Fixture offline')
        return replace(source, revision=self.revision)

    async def materialize(self, source, destination):
        shutil.copytree(self.root, destination)
        return destination

    async def aclose(self):
        pass


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'home'))
    monkeypatch.setattr(settings, 'ms_agent_llm_model', '')
    root = tmp_path / 'upstream' / 'fixture'
    root.mkdir(parents=True)
    (root / 'SKILL.md'
     ).write_text('---\nname: fixture\ndescription: Example\n---\nOriginal')
    provider = Source(root.parent)
    monkeypatch.setattr(
        'ms_agent.skill.management.service.SkillSourceProvider',
        lambda: provider)
    from app.main import create_app
    with TestClient(create_app()) as client:
        yield client, provider


def operation(client, response):
    assert response.status_code == 202, response.text
    row = response.json()['data']
    deadline = time.monotonic() + 10
    while row['status'] in ('queued', 'running'):
        assert time.monotonic() < deadline, row
        time.sleep(.01)
        row = client.get('/api/skills/operations/' + row['id']).json()['data']
    return row


def install(client, scope='global'):
    preview = operation(
        client,
        client.post(
            '/api/skills/sources/inspect',
            json={
                'scope': scope,
                'source': 'https://github.com/fixture/skills'
            }))['result']
    plan = operation(
        client,
        client.post(
            '/api/skills/install-plans',
            json={
                'scope': scope,
                'source_snapshot_id': preview['id'],
                'candidate_ids': [preview['candidates'][0]['id']]
            }))['result']
    result = operation(
        client,
        client.post(
            f"/api/skills/plans/{plan['id']}/apply",
            json={'request_id': 'install'}))
    assert result['status'] == 'succeeded', result
    return next(
        s for s in client.get('/api/skills', params={
            'scope': scope
        }).json()['data'] if s['name'] == 'fixture')


def test_api_collection_preview_selection_and_individual_sources(api, monkeypatch):
    client, provider = api
    original_resolve = provider.resolve

    async def resolve(value):
        return SourceCollection('fixture/tools', value, 'Tools',
                                ['fixture/skills', '@fixture/skills'])

    async def resolve_member(identity):
        source = await original_resolve(identity)
        return replace(source, provider='modelscope', registry_id=identity)

    monkeypatch.setattr(provider, 'resolve', resolve)
    monkeypatch.setattr(provider, 'resolve_member', resolve_member, raising=False)
    preview = operation(client, client.post('/api/skills/sources/inspect', json={
        'scope': 'global',
        'source': 'https://modelscope.cn/collections/fixture/tools'
    }))['result']
    assert preview['source']['kind'] == 'collection'
    assert len(preview['candidates']) == 2
    selected = preview['candidates'][1]
    assert selected['source']['registry_id'] == '@fixture/skills'
    plan = operation(client, client.post('/api/skills/install-plans', json={
        'scope': 'global', 'source_snapshot_id': preview['id'],
        'candidate_ids': [selected['id']]
    }))['result']
    result = operation(client, client.post(
        f"/api/skills/plans/{plan['id']}/apply", json={'request_id': 'collection'}))
    assert result['status'] == 'succeeded'
    installed = client.get('/api/skills', params={'scope': 'global'}).json()['data']
    skill = next(s for s in installed if s['name'] == 'fixture')
    assert skill['installation']['source']['registry_id'] == '@fixture/skills'
    assert 'kind' not in skill['installation']['source']


def test_api_install_update_local_replace_restore_and_delete(api):
    client, source = api
    skill = install(client)
    sid = skill['id']
    assert skill['installation']['source']['revision'] == source.revision
    assert client.get(
        '/api/skills/'
        + sid).json()['data']['installation'] == skill['installation']
    path = management.service().tree(
        management.sdk_scope('global')) / 'fixture'
    (path / 'custom.md').write_text('Local notes')
    (source.root / 'fixture/SKILL.md'
     ).write_text('---\nname: fixture\ndescription: Example\n---\nUpdated')
    source.revision = 'b' * 40
    check = operation(
        client,
        client.post(
            '/api/skills/update-checks',
            json={
                'scope': 'global',
                'force': True
            }))
    assert check['result'][0]['remote_status'] == 'available'
    assert check['result'][0]['local_status'] == 'modified'
    plan = operation(client,
                     client.post(f'/api/skills/{sid}/update-plans'))['result']
    diff = client.get(
        f"/api/skills/plans/{plan['id']}/diff",
        params={
            'item_id': plan['items'][0]['id'],
            'path': 'SKILL.md'
        }).json()['data']
    assert '+Updated' in diff['diff'] and '-Original' in diff['diff']
    response = operation(
        client,
        client.post(
            f"/api/skills/plans/{plan['id']}/apply",
            json={'request_id': 'safe'}))
    assert response['result'][0]['error']['code'] == 'LOCAL_MODIFIED'
    assert (path / 'custom.md').exists()
    with SkillUseLease(
        [management.service().tree(management.sdk_scope('global'))]):
        response = operation(
            client,
            client.post(
                f"/api/skills/plans/{plan['id']}/apply",
                json={
                    'request_id': 'busy',
                    'local_changes_policy': 'replace'
                }))
        assert response['result'][0]['error']['code'] == 'SKILL_BUSY'
        assert client.delete('/api/skills/' + sid).status_code == 409
    response = operation(
        client,
        client.post(
            f"/api/skills/plans/{plan['id']}/apply",
            json={
                'request_id': 'replace',
                'local_changes_policy': 'replace'
            }))
    assert response['status'] == 'succeeded'
    assert not (path / 'custom.md').exists()
    restore = operation(
        client, client.post(f'/api/skills/{sid}/restore-plans'))['result']
    assert operation(
        client,
        client.post(
            f"/api/skills/plans/{restore['id']}/apply",
            json={'request_id': 'restore'}))['status'] == 'succeeded'
    assert (path / 'custom.md').read_text() == 'Local notes'
    source.fail = True
    check = operation(
        client,
        client.post(
            '/api/skills/update-checks',
            json={
                'scope': 'global',
                'force': True
            }))
    assert check['status'] == 'failed'
    assert client.get(
        '/api/skills', params={
            'scope': 'global'
        }).status_code == 200
    assert client.delete('/api/skills/' + sid).status_code == 200
    assert not management.service().installations(
        management.sdk_scope('global'))


def test_project_scope_and_legacy_link_api(api):
    client, source = api
    project = client.get('/api/projects').json()['data'][0]
    scope = 'project:' + project['id']
    skill = install(client, scope)
    assert skill['scope'] == scope
    assert not any(
        s['name'] == 'fixture'
        for s in client.get('/api/skills', params={
            'scope': 'global'
        }).json()['data'])
    assert client.patch(
        '/api/skills/' + skill['id'], json={
            'enabled': False
        }).json()['data']['enabled'] is False
    # A pre-existing managed directory is associated without replacing files.
    target = management.service().tree(
        management.sdk_scope('global')) / 'fixture'
    shutil.copytree(source.root / 'fixture', target)
    management._changed('global')
    legacy = next(
        s for s in client.get('/api/skills', params={
            'scope': 'global'
        }).json()['data'] if s['name'] == 'fixture')
    assert legacy['capabilities']['can_link']
    preview = operation(
        client,
        client.post(
            '/api/skills/sources/inspect',
            json={
                'scope': 'global',
                'source': 'https://github.com/fixture/skills'
            }))['result']
    plan = operation(
        client,
        client.post(
            f"/api/skills/{legacy['id']}/link-plans",
            json={
                'source_snapshot_id': preview['id'],
                'candidate_id': preview['candidates'][0]['id']
            }))['result']
    assert plan['items'][0]['changes'] == []
    assert operation(
        client,
        client.post(
            f"/api/skills/plans/{plan['id']}/apply",
            json={'request_id': 'link'}))['status'] == 'succeeded'
    assert client.get(
        '/api/skills/'
        + legacy['id']).json()['data']['capabilities']['can_update']


def test_download_does_not_block_lists_and_can_be_cancelled(api, monkeypatch):
    client, source = api

    async def slow(source, destination):
        await asyncio.sleep(30)

    monkeypatch.setattr(source, 'materialize', slow)
    row = client.post(
        '/api/skills/sources/inspect',
        json={
            'scope': 'global',
            'source': 'https://github.com/fixture/skills'
        }).json()['data']
    start = time.monotonic()
    assert client.get(
        '/api/skills', params={
            'scope': 'global'
        }).status_code == 200
    assert client.get('/api/health').status_code == 200
    assert time.monotonic() - start < 1
    cancelled = client.delete('/api/skills/operations/'
                              + row['id']).json()['data']
    assert cancelled['status'] == 'cancelled'
