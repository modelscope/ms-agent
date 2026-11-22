# Copyright (c) ModelScope Contributors. All rights reserved.
"""Development delivery identity, privacy, conflicts and interrupted publication."""
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.dev_scripts/webui'))
import check_webui_release as check
import development_version as versions
import oss_distribution as delivery
import publish_webui_release as publish


def test_retry_keeps_version_but_a_new_run_gets_a_new_version():
    assert versions.development_version('1.7.0rc1', '123') == '1.7.0.dev123'
    assert versions.development_version('1.7.0rc1', '124') == '1.7.0.dev124'
    assert versions.development_version('1.6.0', '123', '1.7.0') == '1.7.0.dev123'


@pytest.mark.parametrize('build,base', [('0', ''), ('01', ''), ('x', ''),
                                       ('1', '1.7'), ('1', '1.7.0rc1')])
def test_invalid_development_identity_is_rejected(build, base):
    with pytest.raises(ValueError):
        versions.development_version('1.7.0', build, base)


def test_development_package_cannot_enter_tag_or_pypi_publication(monkeypatch, tmp_path):
    check.check_tag('1.7.0.dev123', '')
    with pytest.raises(ValueError, match='release tags'):
        check.check_tag('1.7.0.dev123', 'v1.7.0.dev123')
    monkeypatch.setattr(publish.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('No PyPI request'))
    with pytest.raises(ValueError, match='release or RC'):
        publish.publish_pypi(tmp_path, {'version': '1.7.0.dev123'})


def test_version_applies_to_python_and_lock_without_dependency_changes(tmp_path):
    (tmp_path / 'ms_agent').mkdir()
    (tmp_path / 'ms_agent/version.py').write_text("__version__ = '1.7.0rc1'\n")
    (tmp_path / 'webui/backend').mkdir(parents=True)
    lock = tmp_path / 'webui/backend/uv.lock'
    text = ('version = 1\n[[package]]\nname = "ms-agent"\nversion = "1.7.0rc1"\n'
            'source = { editable = "../.." }\n[[package]]\nname = "other"\nversion = "2.0"\n')
    lock.write_text(text)
    versions.apply_version(tmp_path, '1.7.0.dev123')
    assert versions.source_version(tmp_path) == '1.7.0.dev123'
    assert lock.read_text() == text.replace('1.7.0rc1', '1.7.0.dev123')
    with pytest.raises(ValueError, match='isolated'):
        versions.apply_version(ROOT, '1.7.0.dev123')


class MemoryStore(delivery.OssStore):
    """Stateful protocol double: use real delivery decisions with injected failures."""
    def __init__(self, root):
        self.state = root
        self.objects = {}
        self.acls = {}
        self.puts = []
        self.fail_latest = False
        self.timeout_after_put = False

    def exists(self, relative):
        return relative in self.objects

    def put(self, relative, file, *, public=False, immutable=True):
        if self.fail_latest and relative == 'channels/dev/latest.json':
            raise delivery.OssError('put-object', 503, 'ServiceUnavailable')
        if immutable and relative in self.objects:
            raise delivery.OssError('put-object', 409, 'FileAlreadyExists')
        self.objects[relative] = file.read_bytes()
        self.acls[relative] = 'public-read' if public else 'private'
        self.puts.append(relative)
        if self.timeout_after_put:
            self.timeout_after_put = False
            # First request committed, automatic retry observes the existing object.
            raise delivery.OssError('put-object', 409, 'FileAlreadyExists')

    def download(self, relative, file):
        file.write_bytes(self.objects[relative])

    def api(self, operation, relative, *args):
        if operation == 'get-object-acl':
            return {'AccessControlList': {'Grant': self.acls[relative]}}
        if operation == 'put-object-acl':
            self.acls[relative] = args[-1]
            return {}
        pytest.fail('Unexpected operation')

    def url(self, relative):
        return 'https://private-location.invalid/' + relative

    def verify_anonymous(self, relative, expected):
        assert self.acls[relative] == 'public-read'
        assert hashlib.sha256(self.objects[relative]).hexdigest() == expected


def release_files(root, build=123, payload=b'verified wheel'):
    directory = root / str(build)
    directory.mkdir(exist_ok=True)
    version = '1.7.0.dev' + str(build)
    wheel = f'ms_agent-{version}-py3-none-any.whl'
    files = {wheel: payload, f'ms_agent-{version}.tar.gz': b'sdist',
             'runtime-requirements.txt': b'locked dependencies'}
    for name, content in files.items():
        (directory / name).write_bytes(content)
    release = {'version': version, 'sdk_commit': 'a' * 40,
               'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    (directory / 'release.json').write_text(json.dumps(release))
    image = dict(release, image_id='sha256:' + 'b' * 64, smoke='passed',
                 wheel_sha256=release['files'][wheel])
    record = directory / 'image.json'
    record.write_text(json.dumps(image))
    receipt = directory / 'published.json'
    receipt.write_text(json.dumps({
        'version': version, 'sdk_commit': release['sdk_commit'],
        'wheel_sha256': image['wheel_sha256'], 'image_id': image['image_id'],
        'image': publish.REGISTRY_IMAGE + ':' + version,
        'image_digest': publish.REGISTRY_IMAGE + '@sha256:' + 'c' * 64}))
    return directory, record, receipt


def test_upload_retry_reuses_same_bytes_and_rejects_conflict(tmp_path, capsys):
    store = MemoryStore(tmp_path)
    directory, *_ = release_files(tmp_path)
    store.timeout_after_put = True
    receipt = delivery.upload_wheel(store, directory)
    delivery.upload_wheel(store, directory)
    assert len(store.puts) == 1
    assert 'channels/dev/latest.json' not in store.objects
    assert 'private-location' not in capsys.readouterr().out
    release_files(tmp_path, payload=b'other wheel')
    with pytest.raises(ValueError, match='refusing overwrite'):
        delivery.upload_wheel(store, directory)
    assert len(store.puts) == 1
    assert receipt['wheel_sha256'] == hashlib.sha256(b'verified wheel').hexdigest()


def test_incomplete_pair_never_updates_latest_and_retry_completes(tmp_path):
    store = MemoryStore(tmp_path)
    directory, record, receipt = release_files(tmp_path)
    receipt.unlink()
    with pytest.raises(FileNotFoundError):
        delivery.complete_delivery(store, directory, record, receipt)
    assert 'channels/dev/latest.json' not in store.objects
    release_files(tmp_path)
    store.fail_latest = True
    with pytest.raises(delivery.OssError):
        delivery.complete_delivery(store, directory, record, receipt)
    assert 'channels/dev/latest.json' not in store.objects
    store.fail_latest = False
    delivery.complete_delivery(store, directory, record, receipt)
    delivery.complete_delivery(store, directory, record, receipt)
    assert store.puts.count('channels/dev/latest.json') == 1
    assert store.acls['channels/dev/latest.json'] == 'private'
    assert store.acls['builds/1.7.0.dev123/manifest.json'] == 'private'
    assert (tmp_path / 'latest.json').stat().st_mode & 0o777 == 0o600


def test_retry_of_older_build_does_not_roll_back_latest(tmp_path):
    store = MemoryStore(tmp_path)
    older = release_files(tmp_path, 123)
    newer = release_files(tmp_path, 124)
    delivery.complete_delivery(store, *newer)
    delivery.complete_delivery(store, *older)
    assert store.read_json('channels/dev/latest.json')['build_id'] == 124
    assert json.loads((tmp_path / 'latest.json').read_text())['build_id'] == 124


def test_receipt_for_another_wheel_is_rejected_before_upload(tmp_path):
    store = MemoryStore(tmp_path)
    directory, record, receipt = release_files(tmp_path)
    data = json.loads(receipt.read_text()); data['wheel_sha256'] = 'd' * 64
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='does not match'):
        delivery.complete_delivery(store, directory, record, receipt)
    assert not store.puts


@pytest.mark.parametrize('immutable,flag', [(False, '--forbid-overwrite=false'),
                                         (True, '--forbid-overwrite=true')])
def test_oss_overwrite_boolean_is_passed_as_one_cli_argument(tmp_path, monkeypatch, immutable, flag):
    """ossutil treats a bare boolean flag as true, even with a separate 'false'."""
    store = object.__new__(delivery.OssStore)
    store.binary, store.config, store.state = Path('/ossutil'), tmp_path / 'config', tmp_path
    store.region, store.endpoint = 'cn-beijing', 'https://oss-cn-beijing.aliyuncs.com'
    store.bucket, store.prefix = 'example-bucket', 'packages/'
    file = tmp_path / 'record.json'
    file.write_text('{}')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(subprocess, 'run', run)
    store.put('record.json', file, immutable=immutable)
    assert len(commands) == 1
    assert [arg for arg in commands[0] if arg.startswith('--forbid-overwrite')] == [flag]


def test_raw_oss_errors_and_subprocess_arguments_are_not_exposed(tmp_path, monkeypatch):
    store = object.__new__(delivery.OssStore)
    store.binary, store.config, store.state = Path('/ossutil'), Path('/private/config'), tmp_path
    store.region = 'cn-beijing'
    store.endpoint = 'https://oss-cn-beijing.aliyuncs.com'
    raw = 'StatusCode: 403 ErrorCode: AccessDenied URL=https://private-location.invalid/ AK=private-value'
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', raw))
    with pytest.raises(delivery.OssError) as error:
        store._run('upload', ['cp', 'oss://private-location/file', 'local'])
    assert error.value.status == 403
    assert error.value.code == 'AccessDenied'
    assert 'private-location' not in str(error.value)
    assert 'private-value' not in str(error.value)


def test_transient_transport_retry_allows_time_for_large_wheel(tmp_path, monkeypatch):
    store = object.__new__(delivery.OssStore)
    store.binary, store.config, store.state = Path('/ossutil'), Path('/private/config'), tmp_path
    store.region = 'cn-beijing'
    store.endpoint = 'https://oss-cn-beijing.aliyuncs.com'
    calls = []
    def run(command, **kwargs):
        calls.append(kwargs['timeout'])
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(delivery.time, 'sleep', lambda _: None)
    assert store._run('put-object', ['api', 'put-object']) == '{}'
    assert calls == [600, 600]
    store._run('head-object', ['api', 'head-object'])
    assert calls[-1] == 120


def test_anonymous_download_retries_network_failure_without_credentials(monkeypatch):
    store = object.__new__(delivery.OssStore)
    store.url = lambda _: 'https://private-location.invalid/wheel.whl'
    class Response(io.BytesIO):
        status = 200
        def geturl(self):
            return store.url('')
    class Opener:
        calls = 0
        def open(self, url, timeout):
            assert isinstance(url, str)  # No Request carrying authorization headers.
            self.calls += 1
            if self.calls == 1:
                raise delivery.urllib.error.URLError('private-location connection interrupted')
            return Response(b'wheel')
    opener = Opener()
    monkeypatch.setattr(delivery.urllib.request, 'build_opener', lambda *a: opener)
    monkeypatch.setattr(delivery.time, 'sleep', lambda _: None)
    store.verify_anonymous('wheel.whl', hashlib.sha256(b'wheel').hexdigest())
    assert opener.calls == 2


def test_missing_ca_fails_without_disabling_tls_or_repeating_request(monkeypatch):
    store = object.__new__(delivery.OssStore)
    store.url = lambda _: 'https://private-location.invalid/wheel.whl'
    class Opener:
        def open(self, *args, **kwargs):
            raise delivery.urllib.error.URLError(
                delivery.ssl.SSLCertVerificationError(1, 'private-location certificate rejected'))
    monkeypatch.setattr(delivery.urllib.request, 'build_opener', lambda *a: Opener())
    monkeypatch.setattr(delivery.time, 'sleep', lambda _: pytest.fail('Certificate errors are not transient'))
    with pytest.raises(delivery.OssError, match='CertificateVerifyFailed'):
        store.verify_anonymous('wheel.whl', hashlib.sha256(b'wheel').hexdigest())


@pytest.mark.parametrize('race', [False, True])
def test_large_wheel_stages_privately_and_copy_cannot_overwrite(tmp_path, race):
    store = object.__new__(delivery.OssStore)
    store.state, store.bucket, store.prefix = tmp_path, 'private-bucket', 'prefix/'
    file = tmp_path / 'wheel.whl'
    file.write_bytes(b'w' * (4 * 1024 * 1024))
    events = []
    def run(operation, arguments):
        assert operation == 'upload'
        assert arguments[arguments.index('--acl') + 1] == 'private'
        assert arguments[arguments.index('--parallel') + 1] == '16'
        events.append('private upload')
    def api(operation, relative, *arguments):
        events.append(operation)
        if operation == 'copy-object':
            assert '--forbid-overwrite=true' in arguments
            assert arguments[arguments.index('--object-acl') + 1] == 'public-read'
            if race:
                raise delivery.OssError(operation, 409, 'FileAlreadyExists')
        elif operation == 'delete-object':
            assert relative.startswith('staging/')
        else:
            pytest.fail('Unexpected operation')
    store._run, store.api = run, api
    store.matches = lambda relative, expected: relative.startswith('staging/') and expected == delivery.sha256(file)
    if race:
        with pytest.raises(delivery.OssError, match='FileAlreadyExists'):
            store.put('builds/wheel.whl', file, public=True)
    else:
        store.put('builds/wheel.whl', file, public=True)
    assert events == ['private upload', 'copy-object', 'delete-object']


@pytest.mark.parametrize('status,code', [(403, 'AccessDenied'), (404, 'NoSuchBucket'),
                                      (503, 'ServiceUnavailable')])
def test_head_errors_are_not_mistaken_for_missing_objects(status, code):
    store = object.__new__(delivery.OssStore)
    def fail(*args):
        raise delivery.OssError('head-object', status, code)
    store.api = fail
    with pytest.raises(delivery.OssError):
        store.exists('wheel.whl')


def test_workflow_business_delivery_is_opt_in_and_follows_image_publication():
    import yaml
    load = lambda name: yaml.load((ROOT / '.github/workflows' / name).read_text(), Loader=yaml.BaseLoader)
    entry = load('webui-image.yaml')
    assert entry['on']['workflow_dispatch']['inputs']['push_dev']['default'] == 'false'
    assert entry['jobs']['push-dev']['with']['publish_wheel'] == 'true'
    assert entry['jobs']['push-dev']['with']['image_tag'] == '${{ needs.package.outputs.version }}'
    steps = load('webui-image-runner.yaml')['jobs']['image']['steps']
    upload = next(i for i, step in enumerate(steps) if 'oss_distribution.py upload' in step.get('run', ''))
    image = next(i for i, step in enumerate(steps) if '--receipt ' in step.get('run', ''))
    complete = next(i for i, step in enumerate(steps) if 'oss_distribution.py complete' in step.get('run', ''))
    assert upload < image < complete
    assert 'inputs.publish_wheel' in steps[upload]['if']
    assert 'inputs.publish_wheel' in steps[complete]['if']


@pytest.mark.parametrize('value', [None, '', 'relative/config'])
def test_oss_cli_requires_explicit_absolute_configuration(value, monkeypatch, capsys):
    if value is None:
        monkeypatch.delenv('MS_AGENT_OSS_ROOT', raising=False)
    else:
        monkeypatch.setenv('MS_AGENT_OSS_ROOT', value)
    monkeypatch.setattr(sys, 'argv', ['oss_distribution.py', 'upload', '--inputs', 'unused'])
    monkeypatch.setattr(delivery, 'OssStore', lambda _: pytest.fail('Do not access guessed configuration'))
    with pytest.raises(SystemExit) as error:
        delivery.main()
    assert error.value.code == 2
    assert 'MS_AGENT_OSS_ROOT' in capsys.readouterr().err


@pytest.mark.parametrize('explicit', [False, True])
def test_oss_cli_uses_environment_or_explicit_override(tmp_path, monkeypatch, explicit):
    environment = tmp_path / 'environment'
    override = tmp_path / 'override'
    monkeypatch.setenv('MS_AGENT_OSS_ROOT', str(environment))
    argv = ['oss_distribution.py', 'upload', '--inputs', str(tmp_path)]
    if explicit:
        argv += ['--config-root', str(override)]
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(delivery.os, 'umask', lambda _: None)
    selected = []
    monkeypatch.setattr(delivery, 'OssStore', lambda root: selected.append(root))
    monkeypatch.setattr(delivery, 'upload_wheel', lambda *a: None)
    delivery.main()
    assert selected == [override if explicit else environment]


def test_runner_configuration_is_required_only_for_publication(tmp_path):
    import yaml
    workflow = yaml.load((ROOT / '.github/workflows/webui-image-runner.yaml').read_text(), Loader=yaml.BaseLoader)
    script = next(s['run'] for s in workflow['jobs']['image']['steps']
                  if s.get('name') == 'Resolve publication configuration')
    output = tmp_path / 'github-env'
    base = {key: value for key, value in os.environ.items()
            if key not in ('MS_AGENT_ACR_AUTH_FILE', 'MS_AGENT_OSS_ROOT')}
    base.update(GITHUB_ENV=str(output), REPOSITORY_ACR_AUTH_FILE='', REPOSITORY_OSS_ROOT='',
                SELECTED_TAG='', PUBLISH_WHEEL='false')
    def run(**values):
        output.write_text('')
        return subprocess.run(['bash', '-c', script], env={**base, **values}, capture_output=True, text=True)
    assert run().returncode == 0
    missing = run(SELECTED_TAG='1.7.0.dev123')
    assert missing.returncode != 0 and 'MS_AGENT_ACR_AUTH_FILE' in missing.stderr
    acr = tmp_path / 'docker-auth.json'
    acr.write_text('{}')
    missing = run(SELECTED_TAG='1.7.0.dev123', MS_AGENT_ACR_AUTH_FILE=str(acr), PUBLISH_WHEEL='true')
    assert missing.returncode != 0 and 'MS_AGENT_OSS_ROOT' in missing.stderr
    assert run(SELECTED_TAG='1.7.0.dev123', PUBLISH_WHEEL='true',
               MS_AGENT_ACR_AUTH_FILE=str(acr), MS_AGENT_OSS_ROOT=str(tmp_path)).returncode == 0
    assert f'ACR_AUTH_FILE={acr}\n' in output.read_text()
    override = tmp_path / 'repository-auth.json'
    override.write_text('{}')
    assert run(SELECTED_TAG='1.7.0.dev123', PUBLISH_WHEEL='true',
               MS_AGENT_ACR_AUTH_FILE='/missing/runner/file', MS_AGENT_OSS_ROOT='/missing/runner/directory',
               REPOSITORY_ACR_AUTH_FILE=str(override), REPOSITORY_OSS_ROOT=str(tmp_path)).returncode == 0
    assert f'ACR_AUTH_FILE={override}\n' in output.read_text()
    assert f'MS_AGENT_OSS_ROOT={tmp_path}\n' in output.read_text()


@pytest.mark.parametrize('endpoint', [None, 'https://oss-accelerate.aliyuncs.com',
                                    'https://oss-accelerate-overseas.aliyuncs.com'])
def test_transfer_endpoint_preserves_region_and_public_download_url(tmp_path, monkeypatch, endpoint):
    config = tmp_path / 'credentials.ini'
    config.write_text('[profile ms-agent]\nmode=AK\nencryptCredential=true\nregion=cn-beijing\n')
    config.chmod(0o600)
    destination = tmp_path / 'destination.json'
    values = {'uri': 'oss://example-bucket/packages/'}
    if endpoint:
        values['endpoint'] = endpoint
    destination.write_text(json.dumps(values))
    destination.chmod(0o600)
    store = delivery.OssStore(tmp_path)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, '{}', '')
    monkeypatch.setattr(subprocess, 'run', run)
    store._run('upload', ['cp', 'wheel.whl', 'oss://example-bucket/packages/wheel.whl'])
    command = commands[0]
    assert command[command.index('--endpoint') + 1] == (endpoint or 'https://oss-cn-beijing.aliyuncs.com')
    assert command[command.index('--region') + 1] == 'cn-beijing'
    assert store.url('wheel.whl') == 'https://example-bucket.oss-cn-beijing.aliyuncs.com/packages/wheel.whl'


@pytest.mark.parametrize('endpoint', ['http://oss-accelerate.aliyuncs.com',
                                    'https://example-bucket.oss-accelerate.aliyuncs.com',
                                    'https://untrusted.invalid',
                                    'https://oss-us-west-1.aliyuncs.com',
                                    'https://oss-accelerate.aliyuncs.com/path'])
def test_transfer_endpoint_rejects_credential_redirection(tmp_path, endpoint):
    config = tmp_path / 'credentials.ini'
    config.write_text('[profile ms-agent]\nmode=AK\nencryptCredential=true\nregion=cn-beijing\n')
    config.chmod(0o600)
    destination = tmp_path / 'destination.json'
    destination.write_text(json.dumps({'uri': 'oss://example-bucket/packages/', 'endpoint': endpoint}))
    destination.chmod(0o600)
    with pytest.raises(ValueError, match='endpoint'):
        delivery.OssStore(tmp_path)
