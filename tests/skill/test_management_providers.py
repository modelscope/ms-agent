"""Source identity, pinning and credential boundaries at the HTTP interface."""
import asyncio
import io
import zipfile

import httpx
import pytest

from ms_agent.skill.management import ManagedSource, SkillManagementError
from ms_agent.skill.management.providers import SkillSourceProvider


def archive():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        bundle.writestr(
            'repo/SKILL.md',
            '---\nname: sample\ndescription: Example\n---\nInstructions')
        bundle.writestr('repo/asset.bin', b'\x00\xff')
    return stream.getvalue()


def test_github_branch_with_slashes_and_fixed_archive(tmp_path):
    seen = []

    def respond(request):
        seen.append(request)
        path = request.url.path
        if path == '/repos/example/skills':
            return httpx.Response(200, json={'default_branch': 'main'})
        if path == '/repos/example/skills/git/ref/heads/feature/new':
            return httpx.Response(200, json={'ref': 'refs/heads/feature/new'})
        if path == '/repos/example/skills/commits/feature/new':
            return httpx.Response(200, json={'sha': 'a' * 40})
        if request.url.host == 'codeload.github.com':
            return httpx.Response(200, content=archive())
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            provider = SkillSourceProvider(client)
            source = await provider.resolve(
                'https://github.com/example/skills/tree/feature/new/skills/sample'
            )
            assert source.ref == 'feature/new' and source.subdir == 'skills/sample'
            root = await provider.materialize(source, tmp_path / 'download')
            assert (root / 'asset.bin').read_bytes() == b'\x00\xff'
            assert seen[-1].url.path.endswith('/' + 'a' * 40)

    asyncio.run(run())


def test_modelscope_revision_and_credentials_only_sent_to_its_host(
        tmp_path, monkeypatch):
    monkeypatch.setenv('MODELSCOPE_API_KEY', 'fixture-secret')
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.path.endswith('/repo/files'):
            return httpx.Response(
                200, json={'Data': {
                    'LatestCommitter': {
                        'Id': 'b' * 40
                    }
                }})
        if request.url.host == 'www.modelscope.cn':
            return httpx.Response(
                302,
                headers={'location': 'https://assets.aliyuncs.com/source.zip'})
        return httpx.Response(200, content=archive())

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            provider = SkillSourceProvider(client)
            source = await provider.resolve('@owner/sample')
            assert source.revision == 'b' * 40
            await provider.materialize(source, tmp_path / 'download')
            assert seen[1].url.path.endswith('/' + 'b' * 40)
            assert seen[0].headers['authorization'] == 'Bearer fixture-secret'
            assert 'authorization' not in seen[-1].headers
            assert 'Authorization' not in provider._headers(
                'https://api.github.com/repos/a/b')

    asyncio.run(run())


@pytest.mark.parametrize('url', [
    'http://github.com/a/b', 'https://localhost/a/b',
    'https://user:secret@github.com/a/b', 'https://github.com/a/b?token=x'
])
def test_unsupported_urls_never_make_a_request(url):

    def respond(request):
        pytest.fail('Unsupported URL reached the network')

    async def run():
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(SkillManagementError):
                await SkillSourceProvider(client).resolve(url)

    asyncio.run(run())


@pytest.mark.parametrize('destination', [
    'https://untrusted.example/archive.zip',
    'http://www.modelscope.cn/archive.zip',
    'https://www.modelscope.cn:8443/archive.zip',
    'https://user:password@www.modelscope.cn/archive.zip',
])
def test_redirect_cannot_bypass_credential_boundary(tmp_path, monkeypatch,
                                                    destination):
    monkeypatch.setenv('MODELSCOPE_API_KEY', 'fixture-secret')
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': destination})

    async def run():
        # Even a caller-owned client configured to follow redirects must not
        # bypass provider validation or forward credentials to another origin.
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond),
                follow_redirects=True) as client:
            provider = SkillSourceProvider(client)
            source = ManagedSource(
                'modelscope',
                'owner/sample',
                'master',
                'a' * 40,
                registry_id='owner/sample')
            with pytest.raises(SkillManagementError) as error:
                await provider.materialize(source, tmp_path / 'download')
            assert error.value.code == 'UNSUPPORTED_SOURCE'
            assert len(seen) == 1
            assert 'fixture-secret' not in str(error.value)
            assert 'Authorization' not in provider._headers(destination)

    asyncio.run(run())


@pytest.mark.parametrize('registry_id', ['owner/sample', '@owner/sample'])
def test_modelscope_native_and_mirrored_ids_are_preserved(
        tmp_path, registry_id):
    seen = []
    revision = 'a' * 40

    def respond(request):
        seen.append(request.url.path)
        prefix = '/api/v1/skills/' + registry_id
        if request.url.path == prefix + '/repo/files':
            return httpx.Response(
                200, json={'Data': {
                    'LatestCommitter': {
                        'Id': revision
                    }
                }})
        if request.url.path == prefix + '/archive/zip/' + revision:
            return httpx.Response(200, content=archive())
        return httpx.Response(404)

    async def run():
        nonlocal revision
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            provider = SkillSourceProvider(client)
            source = await provider.resolve('https://modelscope.cn/skills/'
                                            + registry_id)
            assert source.registry_id == registry_id
            root = await provider.materialize(source, tmp_path / 'v1')
            assert (root / 'SKILL.md').is_file()
            revision = 'b' * 40
            latest = await provider.latest(source)
            assert latest.revision == revision and latest.registry_id == registry_id
            await provider.materialize(latest, tmp_path / 'v2')
            assert all(
                path.startswith('/api/v1/skills/' + registry_id + '/')
                for path in seen)

    asyncio.run(run())


def test_modelscope_initial_fallback_does_not_switch_installed_identity():
    seen = []
    removed = False

    def respond(request):
        seen.append(request.url.path)
        if request.url.path == '/api/v1/skills/@owner/sample/repo/files' and not removed:
            return httpx.Response(
                200, json={'Data': {
                    'LatestCommitter': {
                        'Id': 'a' * 40
                    }
                }})
        if request.url.path == '/api/v1/skills/owner/sample/repo/files' and removed:
            pytest.fail(
                'An installed source must not switch to a different registry identity'
            )
        return httpx.Response(404)

    async def run():
        nonlocal removed
        async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)) as client:
            provider = SkillSourceProvider(client)
            source = await provider.resolve(
                'https://modelscope.cn/skills/owner/sample')
            assert source.registry_id == '@owner/sample'
            assert len(seen) == 2
            removed = True
            with pytest.raises(SkillManagementError, match='not found'):
                await provider.latest(source)
            assert len(seen) == 3

    asyncio.run(run())


def test_existing_modelscope_records_keep_the_mirrored_identity():
    previous = ManagedSource('modelscope', 'owner/sample', 'master', 'a' * 40)
    native = ManagedSource(
        'modelscope',
        'owner/sample',
        'master',
        'a' * 40,
        registry_id='owner/sample')
    mirrored = ManagedSource(
        'modelscope',
        'owner/sample',
        'master',
        'a' * 40,
        registry_id='@owner/sample')
    assert previous.identity == mirrored.identity != native.identity
    with pytest.raises(SkillManagementError):
        ManagedSource(
            'modelscope',
            'owner/sample',
            'master',
            'a' * 40,
            registry_id='other/sample')
