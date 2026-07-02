import json
import os
import subprocess
import tarfile
from io import BytesIO

import pytest

from ms_agent.plugins.config_manager import PluginConfigManager
from ms_agent.plugins.installer import (
    PluginInstaller,
    UnsupportedPluginSource,
    _parse_github_uri,
    _verify_resolved_sha,
    normalize_install_source,
    resolve_marketplace_plugin_uri,
    resolve_ms_agent_uri,
)


def _sample_plugin(root):
    (root / '.claude-plugin').mkdir(parents=True)
    (root / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({'name': 'local-demo', 'version': '0.1.0'}),
        encoding='utf-8',
    )
    skill = root / 'skills' / 'writer'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text(
        '---\nname: Writer\ndescription: Write better text.\n---\n',
        encoding='utf-8',
    )


def test_normalize_marketplace_alias_to_github_uri(monkeypatch):
    payload = {
        'plugins': [
            {'name': 'hookify', 'source': './plugins/hookify'},
        ],
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode('utf-8')

    monkeypatch.setattr(
        'ms_agent.plugins.installer.urlopen',
        lambda url, timeout=30: FakeResponse(),
    )

    assert normalize_install_source('hookify@claude-plugins-official') == (
        'github://anthropics/claude-plugins-official@main#plugins/hookify'
    )


def test_resolve_marketplace_plugin_uri_uses_index(monkeypatch):
    payload = {
        'plugins': [
            {'name': 'hookify', 'source': './plugins/hookify'},
        ],
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode('utf-8')

    monkeypatch.setattr(
        'ms_agent.plugins.installer.urlopen',
        lambda url, timeout=30: FakeResponse(),
    )

    uri = resolve_marketplace_plugin_uri('hookify', 'claude-plugins-official')
    assert uri == 'github://anthropics/claude-plugins-official@main#plugins/hookify'


def test_install_local_copies_and_locks_manifest(tmp_path):
    source = tmp_path / 'source-plugin'
    _sample_plugin(source)
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    manifest = installer.install(str(source), scope='global')

    record = manager.get('local-demo', scope='global')
    assert manifest.plugin_id == 'local-demo'
    assert record is not None
    assert record.manifest_path == '.claude-plugin/plugin.json'
    assert record.format == 'claude'
    assert record.enabled is True
    assert (global_dir / 'plugins' / 'local-demo' / 'skills' / 'writer' / 'SKILL.md').is_file()


def test_install_uses_manifest_default_enabled(tmp_path):
    source = tmp_path / 'source-plugin'
    _sample_plugin(source)
    (source / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({
            'name': 'local-demo',
            'version': '0.1.0',
            'defaultEnabled': False,
        }),
        encoding='utf-8',
    )
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    installer.install(str(source), scope='global')

    assert manager.get('local-demo', scope='global').enabled is False


def test_install_github_uri_uses_sparse_checkout(tmp_path, monkeypatch):
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    def fake_run(cmd, check, capture_output=True, text=True):
        if cmd[:3] == ['git', 'clone', '--depth']:
            clone_root = cmd[-1]
            plugin = tmp_path / clone_root / 'plugins' / 'local-demo'
            _sample_plugin(plugin)
        return subprocess.CompletedProcess(cmd, 0, stdout='abc123\n', stderr='')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, 'run', fake_run)

    manifest = installer.install(
        'github://owner/repo@main#plugins/local-demo',
        scope='global',
    )

    assert manifest.plugin_id == 'local-demo'
    record = manager.get('local-demo', scope='global')
    assert record.source.type == 'github'
    assert record.source.uri == 'github://owner/repo@main#plugins/local-demo'


def test_install_github_uri_with_commit_sha(tmp_path, monkeypatch):
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    sha = 'a' * 40
    calls = []

    def fake_run(cmd, check, capture_output=True, text=True):
        calls.append(cmd)
        if cmd[:3] == ['git', 'clone', '--depth']:
            clone_root = cmd[-1]
            plugin = tmp_path / clone_root / 'plugins' / 'local-demo'
            _sample_plugin(plugin)
        return subprocess.CompletedProcess(cmd, 0, stdout=f'{sha}\n', stderr='')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, 'run', fake_run)

    manifest = installer.install(
        f'github://owner/repo@{sha}#plugins/local-demo',
        scope='global',
    )

    assert manifest.plugin_id == 'local-demo'
    clone_dir = calls[0][-1]
    assert '--branch' not in calls[0]
    assert calls[1] == ['git', '-C', clone_dir, 'fetch', 'origin', sha]
    assert calls[2] == ['git', '-C', clone_dir, 'checkout', sha]


def test_parse_github_uri_with_sha_query():
    repo, ref, subdir, expected_sha = _parse_github_uri(
        'github://owner/repo@main#plugins/demo?sha=' + 'b' * 40,
    )
    assert repo == 'owner/repo'
    assert ref == 'main'
    assert subdir == 'plugins/demo'
    assert expected_sha == 'b' * 40


def test_verify_resolved_sha_rejects_mismatch():
    with pytest.raises(UnsupportedPluginSource, match='sha mismatch'):
        _verify_resolved_sha(
            ref='a' * 40,
            expected_sha=None,
            resolved_sha='b' * 40,
        )


def test_install_github_uri_rejects_sha_mismatch(tmp_path, monkeypatch):
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    expected = 'a' * 40

    def fake_run(cmd, check, capture_output=True, text=True):
        if cmd[:3] == ['git', 'clone', '--depth']:
            clone_root = cmd[-1]
            plugin = tmp_path / clone_root / 'plugins' / 'local-demo'
            _sample_plugin(plugin)
        if cmd[-2:] == ['rev-parse', 'HEAD']:
            return subprocess.CompletedProcess(cmd, 0, stdout='b' * 40 + '\n', stderr='')
        return subprocess.CompletedProcess(cmd, 0, stdout='', stderr='')

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(subprocess, 'run', fake_run)

    with pytest.raises(UnsupportedPluginSource, match='sha mismatch'):
        installer.install(
            f'github://owner/repo@{expected}#plugins/local-demo',
            scope='global',
        )


def test_install_modelscope_uri_uses_snapshot_download(tmp_path, monkeypatch):
    source = tmp_path / 'downloaded'
    _sample_plugin(source)
    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    def fake_snapshot_download(model_id, revision=None):
        assert model_id == 'org/pack'
        assert revision == 'v1'
        return str(source)

    import ms_agent.plugins.installer as installer_mod
    monkeypatch.setattr(installer_mod, 'snapshot_download', fake_snapshot_download)

    manifest = installer.install('modelscope://org/pack@v1', scope='global')

    assert manifest.plugin_id == 'local-demo'
    assert manager.get('local-demo', scope='global').source.type == 'modelscope'


def test_install_tarball_rejects_path_traversal(tmp_path):
    archive = tmp_path / 'evil.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo(name='../../evil.txt')
        info.size = 4
        tar.addfile(info, BytesIO(b'evil'))

    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    with pytest.raises(UnsupportedPluginSource, match='Unsafe'):
        installer.install(str(archive), scope='global')


def test_install_tarball_rejects_symlink_member(tmp_path):
    archive = tmp_path / 'evil.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        info = tarfile.TarInfo(name='escape')
        info.type = tarfile.SYMTYPE
        info.linkname = '/etc/passwd'
        tar.addfile(info)

    global_dir = tmp_path / '.ms_agent'
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)

    with pytest.raises(UnsupportedPluginSource, match='Unsafe'):
        installer.install(str(archive), scope='global')


def test_publish_staged_install_restores_broken_symlink_on_failure(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / '.ms_agent' / 'plugins' / 'local-demo'
    staging_root = target.parent / '.staging'
    staging_root.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(tmp_path / 'missing-source', target_is_directory=True)
    staged = staging_root / 'staged-local-demo'
    staged.mkdir()

    original_rename = type(staged).rename

    def fail_staged_rename(self, target_path):
        if self == staged:
            raise RuntimeError('publish failed')
        return original_rename(self, target_path)

    monkeypatch.setattr(type(staged), 'rename', fail_staged_rename)

    with pytest.raises(RuntimeError):
        PluginInstaller._publish_staged_install(staged, target)

    assert target.is_symlink()
    assert os.readlink(target) == str(tmp_path / 'missing-source')
