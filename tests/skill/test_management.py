"""Lifecycle contracts: real files and transactions, deterministic upstream."""
import asyncio
import io
import json
import shutil
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from ms_agent.skill.management import (ManagedSource, SkillManagementError,
                                       SkillManagementService, SkillScope,
                                       SkillUseLease)
from ms_agent.skill.management.content import (copy_content, extract_archive,
                                               file_diff, manifest)


def write_skill(root, name='sample', text='First version'):
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    (path / 'SKILL.md').write_text(
        f'---\nname: {name}\ndescription: A sample skill\n---\n{text}\n')
    (path / 'asset.bin').write_bytes(b'\x00\xff\x01')
    return path


class Provider:

    def __init__(self, root):
        self.root = root
        self.revision = 'a' * 40
        self.downloads = 0
        self.fail = False

    async def resolve(self, source):
        return ManagedSource(
            'github',
            'example/skills',
            'main',
            self.revision,
            url='https://github.com/example/skills')

    async def latest(self, source):
        if self.fail:
            raise SkillManagementError('SOURCE_UNAVAILABLE', 'Offline')
        return replace(source, revision=self.revision)

    async def materialize(self, source, destination):
        self.downloads += 1
        shutil.copytree(self.root, destination)
        return destination

    async def aclose(self):
        pass


def test_checks_do_not_merge_native_and_mirrored_modelscope_repositories(
        tmp_path):
    roots = {}
    for label in ('native', 'mirrored'):
        roots[label] = tmp_path / label
        write_skill(roots[label], name=label)

    class RegistryProvider(Provider):

        async def resolve(self, label):
            return ManagedSource(
                'modelscope',
                'owner/sample',
                'master',
                'a' * 40,
                registry_id='owner/sample'
                if label == 'native' else '@owner/sample')

        async def latest(self, source):
            return replace(
                source,
                revision=('b' if source.registry_id.startswith('@') else 'c')
                * 40)

        async def materialize(self, source, destination):
            label = 'mirrored' if source.registry_id.startswith(
                '@') else 'native'
            shutil.copytree(roots[label], destination)
            return destination

    async def run():
        service = SkillManagementService(
            str(tmp_path / 'home'), RegistryProvider(tmp_path))
        scope = SkillScope()
        try:
            for label in ('native', 'mirrored'):
                preview = await service.inspect_source(scope, label)
                plan = await service.prepare_install(
                    scope, preview.id, [preview.candidates[0].id])
                result = await service.apply_plan(plan.id, request_id=label)
                assert result[0].status == 'succeeded'
                (roots[label] / label / 'SKILL.md').write_text(
                    f'---\nname: {label}\ndescription: Updated\n---\nSecond version'
                )
            result = await service.check_updates(scope, force=True)
            assert len(result) == 2
            assert {row['remote_status'] for row in result} == {'available'}
            assert {row['latest']['revision']
                    for row in result} == {'b' * 40, 'c' * 40}
        finally:
            await service.aclose()

    asyncio.run(run())


@pytest.fixture
def setup(tmp_path, monkeypatch):
    upstream = tmp_path / 'upstream'
    write_skill(upstream)
    monkeypatch.setattr(
        'ms_agent.config.skills_manager.global_standard_skills_tree',
        lambda: tmp_path / 'empty')
    provider = Provider(upstream)
    service = SkillManagementService(str(tmp_path / 'home'), provider)
    return service, provider, SkillScope()


async def install(service, scope):
    preview = await service.inspect_source(
        scope, 'https://github.com/example/skills')
    plan = await service.prepare_install(scope, preview.id,
                                         [x.id for x in preview.candidates])
    result = await service.apply_plan(plan.id, request_id='install')
    assert all(x.status == 'succeeded' for x in result), result
    return result


def test_install_update_restore_preserves_binary_disabled_and_local_customization(
        setup):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        target = service.tree(scope) / 'sample'
        assert (target / 'asset.bin').read_bytes() == b'\x00\xff\x01'
        service.config.set_skill_enabled('sample', False)
        (target / 'team.md').write_text('Local rules')
        write_skill(provider.root, text='Second version')
        provider.revision = 'b' * 40
        checked = await service.check_updates(scope, force=True)
        assert checked[0]['remote_status'] == 'available'
        assert checked[0]['local_status'] == 'modified'
        plan = await service.prepare_update(scope, identity)
        assert any(x.path == 'team.md' and x.kind == 'removed'
                   for x in plan.items[0].changes)
        blocked = await service.apply_plan(plan.id, request_id='blocked')
        assert blocked[0].error['code'] == 'LOCAL_MODIFIED'
        result = await service.apply_plan(
            plan.id, request_id='confirmed', local_changes_policy='replace')
        assert result[0].status == 'succeeded'
        assert not (target / 'team.md').exists()
        assert 'sample' in service.config.load_global()['disabled']
        restored = await service.prepare_restore(scope, identity)
        result = await service.apply_plan(restored.id, request_id='restore')
        assert result[0].status == 'succeeded'
        assert (target / 'team.md').read_text() == 'Local rules'
        assert service.installation(
            scope, identity)['update']['local_status'] == 'modified'
        assert 'sample' in service.config.load_global()['disabled']

    asyncio.run(run())


def test_install_multi_select_and_partial_conflict_retry(setup):

    async def run():
        service, provider, scope = setup
        write_skill(provider.root, 'second')
        preview = await service.inspect_source(scope, 'source')
        plan = await service.prepare_install(
            scope, preview.id, [x.id for x in preview.candidates])
        write_skill(service.tree(scope), 'second', 'Existing user content')
        results = await service.apply_plan(plan.id, request_id='batch')
        assert [x.status for x in results] == ['succeeded', 'failed']
        assert results[1].error['code'] == 'NAME_CONFLICT'
        assert 'Existing user content' in (service.tree(scope)
                                           / 'second/SKILL.md').read_text()
        shutil.rmtree(service.tree(scope) / 'second')
        retry = await service.apply_plan(plan.id, request_id='retry')
        assert all(x.status == 'succeeded' for x in retry)
        assert retry[0].installation_id == results[0].installation_id
        assert len(service.installations(scope)) == 2

    asyncio.run(run())


def test_preview_pins_download_and_local_edit_invalidates_confirmation(setup):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        write_skill(provider.root, text='Previewed version')
        plan = await service.prepare_update(scope, identity)
        write_skill(provider.root, text='New upstream after preview')
        assert (await
                service.apply_plan(plan.id,
                                   request_id='pin'))[0].status == 'succeeded'
        path = service.tree(scope) / 'sample/SKILL.md'
        assert 'Previewed version' in path.read_text()
        plan = await service.prepare_update(scope, identity)
        path.write_text(path.read_text() + '\nConcurrent edit')
        result = await service.apply_plan(
            plan.id, request_id='stale', local_changes_policy='replace')
        assert result[0].error['code'] == 'PLAN_STALE'
        assert 'Concurrent edit' in path.read_text()

    asyncio.run(run())


def test_update_busy_while_read_lease_and_works_after_release(setup):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        write_skill(provider.root, text='Update')
        provider.revision = 'b' * 40
        plan = await service.prepare_update(scope, identity)
        with SkillUseLease([service.tree(scope)]):
            result = await service.apply_plan(plan.id, request_id='busy')
            assert result[0].error['code'] == 'SKILL_BUSY'
            assert (await service.check_updates(
                scope, force=True))[0]['remote_status'] == 'available'
        assert (await
                service.apply_plan(plan.id,
                                   request_id='idle'))[0].status == 'succeeded'

    asyncio.run(run())


def test_source_check_reuses_download_and_ignores_other_skill_change(setup):

    async def run():
        service, provider, scope = setup
        write_skill(provider.root, 'second')
        await install(service, scope)
        before = provider.downloads
        write_skill(provider.root, 'second', 'Changed')
        provider.revision = 'b' * 40
        result = await service.check_updates(scope, force=True)
        assert sorted(x['remote_status']
                      for x in result) == ['available', 'current']
        assert provider.downloads == before + 1
        provider.fail = True
        result = await service.check_updates(scope, force=True)
        assert all(x['remote_status'] == 'failed' for x in result)
        assert any(x['last_known_status'] == 'available' for x in result)

    asyncio.run(run())


def test_project_scope_and_new_target_are_bound_to_plan(setup, tmp_path):

    async def run():
        service, provider, _ = setup
        scope = SkillScope(str(tmp_path / 'project'))
        preview = await service.inspect_source(scope, 'source')
        with pytest.raises(SkillManagementError, match='location changed'):
            await service.prepare_install(SkillScope(), preview.id,
                                          [preview.candidates[0].id])
        result = await install(service, scope)
        assert (service.tree(scope) / 'sample/SKILL.md').is_file()
        assert not service.installations(SkillScope())
        assert result[0].installation_id in service.installations(scope)

    asyncio.run(run())


def test_damaged_and_future_records_are_not_reset(setup):
    service, _, scope = setup
    path = service._records_path(scope)
    path.parent.mkdir(parents=True)
    for content in ('{broken', '{"schema_version":99,"installations":{}}'):
        path.write_text(content)
        with pytest.raises(SkillManagementError):
            service.installations(scope)
        assert path.read_text() == content


@pytest.mark.parametrize(
    'name',
    ['../escape', '/escape', 'a/../../escape', 'a\\escape', 'C:/escape'])
def test_archive_paths_rejected(tmp_path, name):
    archive = tmp_path / 'source.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr(name, 'unsafe')
    with pytest.raises(SkillManagementError):
        extract_archive(archive, tmp_path / 'unpack')


def test_fingerprint_covers_binary_hidden_user_files_and_exec_bits(tmp_path):
    skill = write_skill(tmp_path)
    baseline = manifest(skill)[0]
    (skill / '__pycache__').mkdir()
    (skill / '__pycache__/ignored.pyc').write_bytes(b'cache')
    assert manifest(skill)[0] == baseline
    (skill / '.user-notes').write_text('keep')
    assert manifest(skill)[0] != baseline
    (skill / '.user-notes').unlink()
    (skill / 'asset.bin').write_bytes(b'\x00\xfe\x01')
    assert manifest(skill)[0] != baseline
    (skill / 'asset.bin').write_bytes(b'\x00\xff\x01')
    previous = tmp_path / 'previous'
    copy_content(skill, previous)
    (skill / 'SKILL.md').chmod(0o755)
    assert manifest(skill)[0] != baseline
    assert file_diff(
        previous, skill,
        'SKILL.md')['diff'] == ('old mode 100644\nnew mode 100755')


def test_unchanged_revision_avoids_archive_download(setup):

    async def run():
        service, provider, scope = setup
        await install(service, scope)
        count = provider.downloads
        assert (await service.check_updates(
            scope, force=True))[0]['remote_status'] == 'current'
        assert provider.downloads == count

    asyncio.run(run())


@pytest.mark.parametrize('same', [True, False])
def test_link_legacy_skill_requires_explicit_replace_and_restores_unknown_baseline(
        setup, same):

    async def run():
        service, provider, scope = setup
        tree = service.tree(scope)
        write_skill(
            tree,
            text='First version' if same else 'Local custom instructions')
        original = manifest(tree / 'sample')[0]
        inode = (tree / 'sample').stat().st_ino
        preview = await service.inspect_source(scope, 'source')
        plan = await service.prepare_link(scope, 'sample', preview.id,
                                          preview.candidates[0].id)
        result = await service.apply_plan(plan.id, request_id='link')
        if same:
            assert result[0].status == 'succeeded'
            assert (tree / 'sample').stat().st_ino == inode
            assert not service.installation(
                scope, result[0].installation_id).get('backup')
        else:
            assert result[0].error['code'] == 'BASELINE_UNKNOWN'
            assert not service.installations(scope)
            result = await service.apply_plan(
                plan.id,
                request_id='replace-link',
                local_changes_policy='replace')
            assert result[0].status == 'succeeded'
            restore = await service.prepare_restore(scope,
                                                    result[0].installation_id)
            assert (await service.apply_plan(
                restore.id, request_id='restore'))[0].status == 'succeeded'
            assert manifest(tree / 'sample')[0] == original
            assert service._local_state(
                scope, service.installation(
                    scope, result[0].installation_id))[0] == 'unknown'

    asyncio.run(run())


@pytest.mark.parametrize('failure', ['rename', 'records'])
def test_failed_commit_restores_files_and_records_then_can_retry(
        setup, monkeypatch, failure):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        original = service.installation(scope, identity)
        original_hash = manifest(service.tree(scope) / 'sample')[0]
        write_skill(provider.root, text='Second version')
        plan = await service.prepare_update(scope, identity)
        from ms_agent.skill.management import service as module
        write = module.atomic_write_json
        rename = Path.rename
        armed = True

        def failing_write(path, data, *args, **kwargs):
            nonlocal armed
            if armed and Path(path) == service._records_path(scope):
                armed = False
                raise OSError('Injected record write failure')
            return write(path, data, *args, **kwargs)

        def failing_rename(path, target):
            nonlocal armed
            if armed and path.name == 'incoming':
                armed = False
                raise OSError('Injected rename failure')
            return rename(path, target)

        monkeypatch.setattr(module, 'atomic_write_json',
                            failing_write if failure == 'records' else write)
        monkeypatch.setattr(Path, 'rename',
                            failing_rename if failure == 'rename' else rename)
        assert (await
                service.apply_plan(plan.id,
                                   request_id='failure'))[0].status == 'failed'
        assert service.installation(scope, identity) == original
        assert manifest(service.tree(scope) / 'sample')[0] == original_hash
        assert (await service.apply_plan(
            plan.id, request_id='retry'))[0].status == 'succeeded'

    asyncio.run(run())


def test_install_retry_after_lost_receipt_does_not_duplicate(
        setup, monkeypatch):

    async def run():
        service, _, scope = setup
        preview = await service.inspect_source(scope, 'source')
        plan = await service.prepare_install(scope, preview.id,
                                             [preview.candidates[0].id])
        from ms_agent.skill.management import service as module
        write = module.atomic_write_json
        receipt = service._directory('plans', plan.id) / 'record.json'

        def fail_receipt(path, data, *args, **kwargs):
            if Path(path) == receipt and 'results' in data:
                raise OSError('Lost acknowledgement')
            return write(path, data, *args, **kwargs)

        monkeypatch.setattr(module, 'atomic_write_json', fail_receipt)
        with pytest.raises(OSError):
            await service.apply_plan(plan.id, request_id='first')
        monkeypatch.setattr(module, 'atomic_write_json', write)
        assert (await service.apply_plan(
            plan.id, request_id='retry'))[0].status == 'succeeded'
        assert len(service.installations(scope)) == 1

    asyncio.run(run())


def test_operation_cancel_before_start_and_during_io_preserves_completed_commit(
        setup):
    from ms_agent.skill.management.operations import SkillOperations

    async def run():
        service, _, scope = setup
        operations = SkillOperations(service.root / 'operations')
        called = False

        async def work():
            nonlocal called
            called = True

        operation = operations.submit('preparing', 'global', work)
        assert (await
                operations.cancel(operation['id']))['status'] == 'cancelled'
        assert not called and not operations.tasks
        started = asyncio.Event()

        async def waiting():
            started.set()
            await asyncio.Future()

        operation = operations.submit('checking', 'global', waiting)
        await started.wait()
        assert (await
                operations.cancel(operation['id']))['status'] == 'cancelled'
        assert not operations.tasks

    asyncio.run(run())


def test_cancel_check_joins_owned_download_and_removes_staging(
        setup, monkeypatch):

    async def run():
        service, provider, scope = setup
        await install(service, scope)
        provider.revision = 'b' * 40
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def download(source, destination):
            destination.mkdir(parents=True)
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        monkeypatch.setattr(provider, 'materialize', download)
        task = asyncio.create_task(service.check_updates(scope, force=True))
        await started.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert cancelled.is_set()
        assert not list((service.root / 'checks').glob('*'))
        assert not service._checks

    asyncio.run(run())


def test_crash_recovery_restores_previous_tree_before_next_writer(
        setup, monkeypatch):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        original = service.installation(scope, identity)
        before = manifest(service.tree(scope) / 'sample')[0]
        write_skill(provider.root, text='Updated')
        plan = await service.prepare_update(scope, identity)
        rename = Path.rename

        def fail(path, target):
            if path.name == 'incoming':
                raise OSError('Process stopped after the first rename')
            return rename(path, target)

        with monkeypatch.context() as patch:
            patch.setattr(Path, 'rename', fail)
            patch.setattr(service, '_recover_locked', lambda scope: None)
            assert (await service.apply_plan(
                plan.id, request_id='crash'))[0].status == 'failed'
        assert not (service.tree(scope) / 'sample').exists()
        restarted = SkillManagementService(str(service.root.parent), provider)
        restarted.recover(scope)
        assert manifest(service.tree(scope) / 'sample')[0] == before
        assert restarted.installation(scope, identity) == original
        assert (await restarted.apply_plan(
            plan.id, request_id='retry'))[0].status == 'succeeded'

    asyncio.run(run())


def test_noop_update_preserves_previous_version_backup(setup):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        write_skill(provider.root, text='Updated')
        plan = await service.prepare_update(scope, identity)
        await service.apply_plan(plan.id, request_id='update')
        before = service.installation(scope, identity)
        plan = await service.prepare_update(scope, identity)
        assert not plan.items[0].changes
        assert (await
                service.apply_plan(plan.id,
                                   request_id='noop'))[0].status == 'succeeded'
        after = service.installation(scope, identity)
        assert after['backup'] == before['backup']
        assert after['generation'] == before['generation']

    asyncio.run(run())


def test_two_previews_cannot_overwrite_each_other(setup):

    async def run():
        service, provider, scope = setup
        identity = (await install(service, scope))[0].installation_id
        write_skill(provider.root, text='Updated')
        plans = await asyncio.gather(
            service.prepare_update(scope, identity),
            service.prepare_update(scope, identity))
        results = await asyncio.gather(
            *(service.apply_plan(p.id, request_id=p.id) for p in plans))
        assert sorted(r[0].status for r in results) == ['failed', 'succeeded']
        assert next(r[0] for r in results
                    if r[0].status == 'failed').error['code'] == 'PLAN_STALE'

    asyncio.run(run())


def test_same_check_can_outlive_one_cancelled_subscriber(setup, monkeypatch):

    async def run():
        service, provider, scope = setup
        await install(service, scope)
        entered, release = asyncio.Event(), asyncio.Event()
        original = provider.latest

        async def latest(source):
            entered.set()
            await release.wait()
            return await original(source)

        monkeypatch.setattr(provider, 'latest', latest)
        first = asyncio.create_task(service.check_updates(scope, force=True))
        await entered.wait()
        second = asyncio.create_task(service.check_updates(scope, force=True))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        release.set()
        assert (await second)[0]['remote_status'] == 'current'
        assert not service._checks

    asyncio.run(run())


def test_corrupt_runtime_identity_cannot_target_the_entire_tree(setup):

    async def run():
        service, _, scope = setup
        await install(service, scope)
        path = service._records_path(scope)
        data = json.loads(path.read_text())
        next(iter(data['installations'].values()))['runtime_skill_id'] = '.'
        path.write_text(json.dumps(data))
        with pytest.raises(SkillManagementError) as exc:
            service.installations(scope)
        assert exc.value.code == 'STATE_INVALID'
        assert (service.tree(scope) / 'sample/SKILL.md').is_file()

    asyncio.run(run())


def test_repeated_cancel_waits_for_file_commit(tmp_path):
    import threading
    from ms_agent.skill.management.io import complete_io

    async def run():
        entered, release = threading.Event(), threading.Event()
        target = tmp_path / 'committed'

        def commit():
            entered.set()
            release.wait(5)
            target.write_text('complete')

        task = asyncio.create_task(complete_io(commit))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
            result, = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(result, asyncio.CancelledError)
        assert target.read_text() == 'complete'

    asyncio.run(run())
