# Copyright (c) ModelScope Contributors. All rights reserved.
"""Artifact transfer, interrupted publication and runner credential boundaries."""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.dev_scripts/webui'))
import publish_webui_release as publish
import release_artifacts as artifacts


@pytest.fixture
def release_tree(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    files = {'a.whl': b'wheel', 'a.tar.gz': b'sdist', 'runtime-requirements.txt': b'locked',
             'shell-requirements.txt': b'locked shell tools'}
    for name, data in files.items():
        (inputs / name).write_bytes(data)
    release = {'version': '1.7.0rc0', 'sdk_commit': 'a' * 40,
               'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    (inputs / 'release.json').write_text(json.dumps(release))
    directory = tmp_path / 'image'
    directory.mkdir()
    image = dict(release, image='old-job:local', image_id='sha256:' + 'b' * 64,
                 wheel_sha256=release['files']['a.whl'], smoke='passed')
    record = directory / 'image.json'
    record.write_text(json.dumps(image))
    return inputs, directory, release, image, record


@pytest.mark.parametrize('key,value', [('version', '1.7.0'), ('sdk_commit', 'c' * 40),
                                      ('smoke', 'failed'), ('wheel_sha256', 'wrong'),
                                      ('image_id', 'mutable:tag')])
def test_restore_rejects_other_or_unvalidated_image_before_docker(release_tree, monkeypatch, key, value):
    inputs, directory, _, image, record = release_tree
    image[key] = value
    record.write_text(json.dumps(image))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Docker must not be called'))
    with pytest.raises(ValueError):
        artifacts.restore_image(directory, inputs)


def test_restore_checks_archive_bytes_before_loading(release_tree, monkeypatch):
    inputs, directory, _, image, record = release_tree
    (directory / 'image.tar.gz').write_bytes(b'corrupt archive')
    image['archive_sha256'] = 'expected'
    record.write_text(json.dumps(image))
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Docker must not be called'))
    with pytest.raises(ValueError, match='checksum'):
        artifacts.restore_image(directory, inputs)


@pytest.mark.parametrize('name', ['a.whl', 'shell-requirements.txt'])
def test_changed_package_cannot_be_used_for_image_restore(release_tree, name):
    inputs, directory, *_ = release_tree
    (inputs / name).write_bytes(b'changed input')
    with pytest.raises(ValueError, match='input changed'):
        artifacts.restore_image(directory, inputs)


def test_loaded_identity_is_required_even_if_old_tag_exists(release_tree, monkeypatch):
    _, _, release, image, record = release_tree
    calls = []
    def inspect(command, **kwargs):
        calls.append(command)
        return 'sha256:' + 'c' * 64
    monkeypatch.setattr(subprocess, 'check_output', inspect)
    with pytest.raises(ValueError, match='Loaded image differs'):
        publish.checked_image(release, record)
    assert calls[0][-1] == image['image_id']


def test_pypi_retry_after_partial_upload_does_not_repeat_wheel(release_tree, monkeypatch):
    inputs, _, release, *_ = release_tree
    remote = []
    calls = []
    def response(*args, **kwargs):
        return io.BytesIO(json.dumps({'urls': remote}).encode())
    def upload(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            remote.append({'filename': 'a.whl', 'digests': {'sha256': release['files']['a.whl']}})
            raise subprocess.CalledProcessError(1, command)
        remote.append({'filename': 'a.tar.gz', 'digests': {'sha256': release['files']['a.tar.gz']}})
    monkeypatch.setattr(publish.urllib.request, 'urlopen', response)
    monkeypatch.setattr(subprocess, 'run', upload)
    with pytest.raises(subprocess.CalledProcessError):
        publish.publish_pypi(inputs, release)
    publish.publish_pypi(inputs, release)
    publish.publish_pypi(inputs, release)
    assert len(calls) == 2
    assert calls[1][3:] == [str(inputs / 'a.tar.gz')]


def test_acr_retry_after_push_timeout_accepts_exact_remote_image(release_tree, monkeypatch):
    _, _, release, image, record = release_tree
    pushed = False
    pushes = []
    def run(command, **kwargs):
        nonlocal pushed
        if command[1] == 'pull':
            return subprocess.CompletedProcess(command, 0 if pushed else 1, '', '' if pushed else 'manifest unknown')
        if command[1] == 'push':
            pushes.append(command)
            pushed = True
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(subprocess, 'run', run)
    remote_digest = publish.REGISTRY_IMAGE + '@sha256:' + 'd' * 64
    monkeypatch.setattr(subprocess, 'check_output', lambda command, **k: json.dumps([remote_digest]) if 'RepoDigests' in command[-2] else image['image_id'])
    with pytest.raises(subprocess.CalledProcessError):
        publish.publish_acr(release, record, '1.7.0rc0', push=True)
    receipt = publish.publish_acr(release, record, '1.7.0rc0', push=True)
    assert receipt['image_digest'] == remote_digest
    assert receipt['wheel_sha256'] == image['wheel_sha256']
    assert len(pushes) == 1


@pytest.mark.parametrize('error', ['unauthorized', 'i/o timeout', 'permission denied'])
def test_acr_precheck_failure_never_pushes(release_tree, monkeypatch, error):
    _, _, release, image, record = release_tree
    calls = []
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: image['image_id'])
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, '', error)
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(RuntimeError):
        publish.publish_acr(release, record, '1.7.0rc0', push=True)
    assert all(command[1] == 'pull' for command in calls)


def test_registry_credentials_are_scoped_and_removed_after_failure(tmp_path, monkeypatch, capsys):
    registry = publish.REGISTRY_IMAGE.split('/')[0]
    credential = base64.b64encode(b'test-user:test-password').decode()
    saved = {'auths': {registry: {'auth': credential}, 'other.invalid': {'auth': 'unrelated'}}}
    source = tmp_path / 'shared-config.json'
    source.write_text(json.dumps(saved))
    before = source.read_bytes()
    monkeypatch.setenv('DOCKER_CONFIG', '/previous/config')
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    with pytest.raises(RuntimeError):
        with publish.registry_auth(source):
            temporary = Path(os.environ['DOCKER_CONFIG'])
            config = temporary / 'config.json'
            assert config.stat().st_mode & 0o777 == 0o600
            assert json.loads(config.read_text()) == {'auths': {registry: {'auth': credential}}}
            raise RuntimeError('push failed')
    assert not temporary.exists()
    assert source.read_bytes() == before
    assert os.environ['DOCKER_CONFIG'] == '/previous/config'
    masks = capsys.readouterr().out
    assert '::add-mask::' + credential in masks
    assert '::add-mask::test-password' in masks


def test_global_credential_helper_is_scoped(tmp_path):
    source = tmp_path / 'shared.json'
    source.write_text(json.dumps({'credsStore': 'test-helper'}))
    with publish.registry_auth(source):
        config = json.loads((Path(os.environ['DOCKER_CONFIG']) / 'config.json').read_text())
        assert config['credHelpers'] == {publish.REGISTRY_IMAGE.split('/')[0]: 'test-helper'}
        assert 'credsStore' not in config


@pytest.mark.parametrize('remote,expected', [([], ''), ([{'id': 5, 'name': 'original', 'expired': False}], '5')])
def test_artifact_discovery_reuses_original_run(remote, expected, monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY', 'modelscope/ms-agent')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GH_TOKEN', 'test-token')
    monkeypatch.setattr(artifacts.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(json.dumps({'artifacts': remote}).encode()))
    assert artifacts.find_artifact('original') == expected


def test_expired_artifact_is_not_replaced_with_rebuild(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY', 'modelscope/ms-agent')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GH_TOKEN', 'test-token')
    monkeypatch.setattr(artifacts.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'{"artifacts":[{"id":5,"name":"original","expired":true}]}'))
    with pytest.raises(ValueError, match='expired'):
        artifacts.find_artifact('original')


@pytest.mark.skipif(os.environ.get('RUN_DOCKER_TESTS') != '1', reason='requires a local Docker daemon')
def test_actual_image_archive_recovers_without_any_local_image(release_tree, tmp_path):
    inputs, directory, release, image, record = release_tree
    tag = 'ms-agent-transfer-test:' + uuid.uuid4().hex[:12]
    context = tmp_path / 'context'
    context.mkdir()
    (context / 'payload').write_text('exact artifact recovery')
    (context / 'Dockerfile').write_text('FROM scratch\nCOPY payload /payload\n')
    try:
        subprocess.run(['docker', 'build', '-t', tag, str(context)], check=True, capture_output=True)
        image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag], text=True).strip()
        image.update(image=tag, image_id=image_id)
        record.write_text(json.dumps(image))
        artifacts.save_image(directory, inputs)
        subprocess.run(['docker', 'image', 'rm', tag], check=True, capture_output=True)
        absent = subprocess.run(['docker', 'image', 'inspect', image_id], capture_output=True)
        assert absent.returncode != 0
        recovered = artifacts.restore_image(directory, inputs)
        assert recovered['image_id'] == image_id
        assert publish.checked_image(release, record)['image_id'] == image_id
    finally:
        subprocess.run(['docker', 'image', 'rm', tag], capture_output=True)
        if 'image_id' in locals():
            subprocess.run(['docker', 'image', 'rm', image_id], capture_output=True)


def test_artifact_api_failure_does_not_fall_back_to_rebuilding(monkeypatch):
    monkeypatch.setenv('GITHUB_REPOSITORY', 'modelscope/ms-agent')
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GH_TOKEN', 'test-token')
    def unavailable(*args, **kwargs):
        raise TimeoutError('API unavailable')
    monkeypatch.setattr(artifacts.urllib.request, 'urlopen', unavailable)
    with pytest.raises(TimeoutError):
        artifacts.find_artifact('original')


def test_release_credentials_and_image_jobs_stay_separate():
    import yaml
    root = Path(__file__).resolve().parents[2] / '.github/workflows'
    # BaseLoader keeps the YAML key "on" a string rather than a YAML 1.1 boolean.
    load = lambda name: yaml.load((root / name).read_text(), Loader=yaml.BaseLoader)
    release = load('publish.yaml')['jobs']
    assert release['publish-pypi']['runs-on'].startswith('ubuntu-')
    assert 'PYPI_API_TOKEN' in json.dumps(release['publish-pypi'])
    assert release['publish-image']['needs'] == ['build', 'publish-pypi']
    assert release['publish-image']['with']['operation'] == 'publish'
    for name in ['webui-image.yaml', 'webui-image-runner.yaml']:
        workflow = load(name)
        assert 'pull_request' not in workflow['on']
        assert 'PYPI_API_TOKEN' not in json.dumps(workflow)
        assert all('secrets' not in job for job in workflow['jobs'].values())
    runner = load('webui-image-runner.yaml')['jobs']['image']
    assert runner['runs-on'] == 'ms-agent-image'
    assert "github.repository == 'modelscope/ms-agent'" in runner['if']
    assert "github.event_name == 'workflow_dispatch'" in runner['if']
    checks = load('webui-check.yaml')
    assert 'pull_request' in checks['on']
    assert all(job.get('runs-on', '').startswith('ubuntu-') for job in checks['jobs'].values())
