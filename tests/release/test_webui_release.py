# Copyright (c) ModelScope Contributors. All rights reserved.
"""Release guards must reject version drift and overwriting published bytes."""
import importlib.util
import hashlib
import io
import json
import pytest
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.dev_scripts/webui'))
import check_webui_release as check  # noqa: E402
import publish_webui_release as publish  # noqa: E402
import webui_packaging as packaging  # noqa: E402


@pytest.fixture
def webui_tree(tmp_path, monkeypatch):
    validator = packaging.frontend_validator()
    webui = tmp_path / 'webui'
    (webui / 'frontend').mkdir(parents=True)
    monkeypatch.setattr(packaging, 'WEBUI', webui)
    monkeypatch.setattr(packaging, 'frontend_validator', lambda: validator)
    return webui


def test_new_source_and_data_files_are_included_automatically(webui_tree):
    before = set(packaging.resource_paths(include_build=False))
    new_files = {'backend/app/new_feature.py',
                 'backend/app/data/new_words.txt',
                 'frontend/app/routes/new_page.tsx',
                 'frontend/public/new_icon.svg'}
    for name in new_files:
        file = webui_tree / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('new resource')
    assert set(packaging.resource_paths(include_build=False)) - before == new_files


def test_resource_selection_omits_local_config_and_caches(webui_tree):
    before = packaging.resource_paths(include_build=False)
    for name in ('backend/.env', 'backend/app/.env',
                 'backend/app/__pycache__/main.pyc',
                 'backend/app/main.pyc', 'backend/.venv/local.py',
                 '.claude/skills/local/SKILL.md', 'frontend/local-notes.md',
                 'frontend/node_modules/library/index.js',
                 'frontend/app/.local/note.txt',
                 'frontend/public/antd/manifest.json'):
        file = webui_tree / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('local content')
    assert packaging.resource_paths(include_build=False) == before


def test_unprepared_source_package_keeps_ui_without_build_tools(webui_tree, tmp_path):
    for rel in packaging.resource_paths(include_build=False):
        file = webui_tree / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('source')
    stale = webui_tree / 'frontend/build/server/index.js'
    stale.parent.mkdir(parents=True)
    stale.write_text('unverified output')
    destination = tmp_path / 'wheel/ms_agent/webui'
    packaging.copy_resources(destination)
    manifest = json.loads((destination / packaging.MANIFEST).read_text())
    assert manifest['prebuilt'] is False
    assert manifest['sdk_version'] == packaging.version()
    assert (destination / 'backend/pyproject.toml').is_file()
    assert not (destination / 'frontend/build').exists()
    for rel, digest in manifest['files'].items():
        assert packaging.digest(destination / rel) == digest


def test_existing_invalid_release_manifest_cannot_fall_back_to_source(webui_tree, tmp_path):
    (webui_tree / packaging.MANIFEST).write_text('{}')
    with pytest.raises(RuntimeError, match='missing or stale'):
        packaging.copy_resources(tmp_path / 'wheel')
    assert not (tmp_path / 'wheel').exists()


@pytest.mark.parametrize('prebuilt', [False, True])
def test_publishing_requires_actual_frontend_outputs(tmp_path, prebuilt):
    with zipfile.ZipFile(tmp_path / 'ms_agent-1.7.0-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('ms_agent-1.7.0.dist-info/METADATA', 'Version: 1.7.0\n')
        wheel.writestr('ms_agent/webui/RESOURCE-MANIFEST.json', json.dumps({
            'prebuilt': prebuilt,
            'files': {'frontend/server.js': 'source-hash'},
        }))
    (tmp_path / 'ms_agent-1.7.0.tar.gz').touch()
    with pytest.raises(ValueError, match='require prebuilt WebUI resources'):
        check.check_artifacts(tmp_path, '1.7.0', set(), 'a' * 40)


@pytest.mark.parametrize('lock_state', ['matching', 'changed', 'missing'])
def test_shell_lock_is_verified_and_recorded_in_release_inputs(tmp_path, lock_state):
    version, sha = '1.7.0', 'a' * 40
    rel, content = 'frontend/build/webui-build.json', b'{}'
    manifest = {'prebuilt': True, 'sdk_version': version, 'sdk_commit': sha,
                'files': {rel: hashlib.sha256(content).hexdigest()}}
    with zipfile.ZipFile(tmp_path / 'ms_agent-1.7.0-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('ms_agent-1.7.0.dist-info/METADATA', 'Version: 1.7.0\n')
        wheel.writestr('ms_agent/webui/RESOURCE-MANIFEST.json', json.dumps(manifest))
        wheel.writestr('ms_agent/webui/' + rel, content)
    with tarfile.open(tmp_path / 'ms_agent-1.7.0.tar.gz', 'w:gz') as archive:
        item = tarfile.TarInfo('ms_agent-1.7.0/webui/' + rel)
        item.size = len(content)
        archive.addfile(item, io.BytesIO(content))
    (tmp_path / 'runtime-requirements.txt').write_text('example==1.0\n')
    expected = (ROOT / 'docker/webui-shell.txt').read_bytes()
    if lock_state != 'missing':
        (tmp_path / 'shell-requirements.txt').write_bytes(
            expected if lock_state == 'matching' else b'changed lock')
    if lock_state == 'matching':
        release = check.check_artifacts(tmp_path, version, set(), sha)
        assert release['files']['shell-requirements.txt'] == hashlib.sha256(expected).hexdigest()
        assert 'shell-requirements.txt' in (tmp_path / 'SHA256SUMS').read_text()
    else:
        with pytest.raises(ValueError, match='[Ss]hell|shell-requirements'):
            check.check_artifacts(tmp_path, version, set(), sha)


@pytest.mark.parametrize('name', [
    '../secret', '/tmp/secret', 'build/../../secret',
    'build\\..\\..\\secret'
])
def test_resource_selection_rejects_invalid_build_paths(webui_tree, name):
    manifest = webui_tree / 'frontend/build/webui-build.json'
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({'outputs': {name: 'hash'}}))
    with pytest.raises(RuntimeError, match='Invalid.*path'):
        packaging.resource_paths()


@pytest.mark.parametrize('directory', [False, True])
def test_resource_selection_rejects_symlinks(webui_tree, directory):
    private = webui_tree.parent / 'private'
    if directory:
        private.mkdir()
    else:
        private.write_text('private content')
    app = webui_tree / 'backend/app'
    app.mkdir(parents=True)
    (app / 'config').symlink_to(private, target_is_directory=directory)
    with pytest.raises(RuntimeError, match='Invalid WebUI resource path'):
        packaging.resource_paths(include_build=False)


@pytest.mark.parametrize('version', ['1.7.0rc0', '1.7.0rc1', '1.7.0'])
def test_rc_and_stable_use_the_same_tag_rule(version):
    check.check_tag(version, 'v' + version)


@pytest.mark.parametrize('version,tag', [('1.7.0rc0', 'v1.7.0'),
                                         ('1.7.0', 'v1.7.0rc1'),
                                         ('1.7.0', '1.7.0'),
                                         ('1.7.0-rc0', 'v1.7.0-rc0')])
def test_mismatched_or_ambiguous_tags_fail(version, tag):
    with pytest.raises(ValueError):
        check.check_tag(version, tag)


def test_httpx_requirement_is_not_mistaken_for_a_url(tmp_path):
    spec = importlib.util.spec_from_file_location('sdk_setup',
                                                  ROOT / 'setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requirements = tmp_path / 'requirements.txt'
    requirements.write_text(
        'httpx>=0.28.1\nhttps://example.invalid/tool.whl\n')
    assert module.parse_requirements(str(requirements))[0] == ['httpx>=0.28.1']


def test_pypi_retry_uploads_only_missing_identical_release_files():
    release = {
        'files': {
            'a.whl': 'wheel-hash',
            'a.tar.gz': 'sdist-hash',
            'runtime-requirements.txt': 'lock-hash'
        }
    }
    remote = [{'filename': 'a.whl', 'digests': {'sha256': 'wheel-hash'}}]
    assert publish.pending_packages(release, remote) == ['a.tar.gz']
    remote.append({
        'filename': 'a.tar.gz',
        'digests': {
            'sha256': 'sdist-hash'
        }
    })
    assert publish.pending_packages(release, remote) == []


@pytest.mark.parametrize('filename,digest', [('a.whl', 'other-content'),
                                             ('other.whl', 'wheel-hash')])
def test_pypi_existing_different_content_is_never_skipped(filename, digest):
    with pytest.raises(ValueError):
        publish.pending_packages({'files': {
            'a.whl': 'wheel-hash'
        }}, [{
            'filename': filename,
            'digests': {
                'sha256': digest
            }
        }])


@pytest.mark.parametrize('message', [
    'unauthorized: authentication required', 'dial tcp: i/o timeout',
    'permission denied'
])
def test_acr_connection_and_auth_errors_are_not_absent_tags(
        monkeypatch, message):
    monkeypatch.setattr(
        publish.subprocess, 'run',
        lambda *a, **kw: subprocess.CompletedProcess(a, 1, '', message))
    with pytest.raises(RuntimeError):
        publish.remote_image_exists('example.invalid/image:1.7.0',
                                    'sha256:tested')


def test_acr_cannot_overwrite_a_different_image(monkeypatch):
    monkeypatch.setattr(
        publish.subprocess, 'run',
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, '', ''))
    monkeypatch.setattr(publish.subprocess, 'check_output',
                        lambda *a, **kw: 'sha256:other\n')
    with pytest.raises(ValueError, match='do not overwrite'):
        publish.remote_image_exists('example.invalid/image:1.7.0',
                                    'sha256:tested')
