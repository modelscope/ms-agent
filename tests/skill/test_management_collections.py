"""Collections are discovery snapshots; installations retain individual sources."""
import asyncio
import io
import zipfile

import httpx
import pytest

from ms_agent.skill.management import (ManagedSource, SkillManagementError,
                                       SkillManagementService, SkillScope)
from ms_agent.skill.management.models import SourceCollection
from ms_agent.skill.management.providers import SkillSourceProvider

URL = 'https://modelscope.cn/collections/team/tools'


def member(identity, kind='skill'):
    owner, name = identity.split('/')
    return dict(ElementType=kind, ElementPath=owner, ElementName=name)


def listing(rows, total=None):
    return dict(
        Success=True,
        Data=dict(
            Name='Tools',
            CollectionElements=dict(
                CollectionElementVoList=rows,
                Total=len(rows) if total is None else total)))


def archive(name, revision, plain=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        text = f'# {name}\n{revision}' if plain else (
            f'---\nname: {name}\ndescription: Example\n---\n{revision}')
        bundle.writestr(f'wrapper-{revision}/SKILL.md', text)
        bundle.writestr(f'wrapper-{revision}/asset.bin', b'\x00\xff')
    return stream.getvalue()


def test_collection_pages_filters_deduplicates_and_preserves_registry_identity(
):
    seen = []

    def respond(request):
        seen.append(request)
        page = int(request.url.params['PageNumber'])
        rows = ([member('team/one'), member('team/one')] if page == 1 else
                [member('@team/one'),
                 member('team/model', 'model')])
        return httpx.Response(200, json=listing(rows, 4))

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            source = await SkillSourceProvider(client).resolve(URL)
            assert isinstance(source, SourceCollection)
            assert source.members == ['team/one', '@team/one']
            assert len(seen) == 2
            assert all(r.url.params['ElementType'] == 'skill' for r in seen)

    asyncio.run(run())


@pytest.mark.parametrize('payload,code', [
    (listing([]), 'SKILL_NOT_FOUND'),
    (listing([member('team/model', 'model')]), 'SKILL_NOT_FOUND'),
    (listing([], 101), 'PACKAGE_TOO_LARGE'),
    (listing([member('team/one')] * 101, 1), 'PACKAGE_TOO_LARGE'),
    (dict(Success=False, Data=None), 'SOURCE_UNAVAILABLE'),
    (listing([], 2), 'SOURCE_UNAVAILABLE'),
    (listing([member('team/one')], 3), 'SOURCE_UNAVAILABLE'),
    (listing([member('../one')]), 'UNSUPPORTED_SOURCE'),
])
def test_collection_rejects_empty_oversized_incomplete_and_invalid(
        payload, code):

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=payload))) as client:
            with pytest.raises(SkillManagementError) as caught:
                await SkillSourceProvider(client).resolve(URL)
            assert caught.value.code == code

    asyncio.run(run())


def test_collection_install_independent_update_restore_and_conflicts(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        'ms_agent.config.skills_manager.global_standard_skills_tree',
        lambda: tmp_path / 'empty')
    revisions = {
        'team/alpha': 'a' * 40,
        '@team/alpha': 'a' * 40,
        'team/beta': 'a' * 40
    }
    seen = []

    def respond(request):
        path = request.url.path
        seen.append(path)
        if path == '/api/v1/collections':
            return httpx.Response(
                200,
                json=listing([member(i)
                              for i in [*revisions, 'team/missing']]))
        identity = path.removeprefix('/api/v1/skills/').split(
            '/repo/')[0].split('/archive/')[0]
        if identity not in revisions:
            return httpx.Response(404)
        if path.endswith('/repo/files'):
            return httpx.Response(
                200,
                json=dict(
                    Data=dict(LatestCommitter=dict(Id=revisions[identity]))))
        revision = path.split('/')[-1]
        name = identity.split('/')[-1]
        return httpx.Response(
            200, content=archive(name, revision, plain=name == 'beta'))

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            service = SkillManagementService(
                str(tmp_path / 'home'), SkillSourceProvider(client))
            scope = SkillScope()
            try:
                preview = await service.inspect_source(scope, URL)
                alpha, mirror, beta, missing = preview.candidates
                assert beta.name == beta.runtime_skill_id == 'beta'
                assert missing.error['code'] == 'SOURCE_UNAVAILABLE'
                assert not any('/@team/missing/' in p for p in seen)
                with pytest.raises(
                        SkillManagementError, match='one Skill per name'):
                    await service.prepare_install(scope, preview.id,
                                                  [alpha.id, mirror.id])
                with pytest.raises(
                        SkillManagementError, match='could not be inspected'):
                    await service.prepare_install(scope, preview.id,
                                                  [missing.id])
                with pytest.raises(
                        SkillManagementError, match='location changed'):
                    await service.prepare_install(
                        SkillScope(str(tmp_path / 'project')), preview.id,
                        [alpha.id])
                plan = await service.prepare_install(scope, preview.id,
                                                     [mirror.id, beta.id])
                assert [i.source.registry_id
                        for i in plan.items] == ['@team/alpha', 'team/beta']
                results = await service.apply_plan(plan.id, request_id='batch')
                assert [r.status
                        for r in results] == ['succeeded', 'succeeded']
                assert (service.tree(scope) / 'beta'
                        / 'asset.bin').read_bytes() == b'\x00\xff'
                # Collection membership no longer participates in the lifecycle.
                collection_requests = seen.count('/api/v1/collections')
                revisions['@team/alpha'] = 'b' * 40
                checks = await service.check_updates(scope, force=True)
                assert [c['remote_status']
                        for c in checks] == ['available', 'current']
                update = await service.prepare_update(
                    scope, results[0].installation_id)
                assert update.items[0].source.registry_id == '@team/alpha'
                assert (await service.apply_plan(
                    update.id, request_id='update'))[0].status == 'succeeded'
                restore = await service.prepare_restore(
                    scope, results[0].installation_id)
                assert (await service.apply_plan(
                    restore.id, request_id='restore'))[0].status == 'succeeded'
                assert 'a' * 40 in (service.tree(scope) / 'alpha'
                                    / 'SKILL.md').read_text()
                revisions['team/beta'] = 'c' * 40
                beta_update = await service.prepare_update(
                    scope, results[1].installation_id)
                assert beta_update.items[0].name == 'beta'
                assert (await service.apply_plan(
                    beta_update.id,
                    request_id='beta-update'))[0].status == 'succeeded'
                beta_restore = await service.prepare_restore(
                    scope, results[1].installation_id)
                assert beta_restore.items[0].name == 'beta'
                assert seen.count('/api/v1/collections') == collection_requests
                again = await service.inspect_source(scope, URL)
                assert [c.conflict for c in again.candidates[:3]] == [
                    'NAME_CONFLICT', 'ALREADY_INSTALLED', 'ALREADY_INSTALLED'
                ]
            finally:
                await service.aclose()

    asyncio.run(run())


def test_cancel_collection_joins_children_before_removing_snapshots(tmp_path):

    async def run():
        started = asyncio.Event()
        active = set()
        closed = set()

        class Provider:

            async def resolve(self, _):
                return SourceCollection('team/tools', URL, 'Tools',
                                        ['team/a', 'team/b'])

            async def resolve_member(self, identity):
                return ManagedSource(
                    'modelscope',
                    identity,
                    'master',
                    'a' * 40,
                    registry_id=identity)

            async def materialize(self, source, destination):
                destination.mkdir(parents=True)
                (destination / 'partial.zip').write_bytes(b'partial download')
                identity = source.registry_id
                active.add(identity)
                if len(active) == 2:
                    started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    closed.add(identity)

            async def aclose(self):
                pass

        service = SkillManagementService(str(tmp_path), Provider())
        task = asyncio.create_task(service.inspect_source(SkillScope(), URL))
        await asyncio.wait_for(started.wait(), 2)
        assert len(list((service.root / 'sources').rglob('partial.zip'))) == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed == active == {'team/a', 'team/b'}
        assert not list((service.root / 'sources').iterdir())
        await service.aclose()

    asyncio.run(run())
