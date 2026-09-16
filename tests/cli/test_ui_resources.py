import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from ms_agent.cli import ui_resources as resources
from ms_agent.version import __version__


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / 'installed'
    files = {
        'backend/app/main.py': '# backend',
        'frontend/server.js': '// server',
        'frontend/package.json': json.dumps({'packageManager': 'pnpm@10.17.1'}),
        'frontend/pnpm-lock.yaml': 'lockfileVersion: 9',
    }
    manifest = {'format': 1, 'sdk_version': __version__, 'files': {}}
    for rel, data in files.items():
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(data)
        manifest['files'][rel] = hashlib.sha256(file.read_bytes()).hexdigest()
    (root / 'RESOURCE-MANIFEST.json').write_text(json.dumps(manifest))
    return root, manifest


def test_materialization_uses_only_listed_files(bundle, tmp_path):
    root, manifest = bundle
    (root / '.env').write_text('EXAMPLE_SECRET=do-not-copy')
    destination = tmp_path / 'cache'
    resources.materialize(root, manifest, destination)
    assert not (destination / '.env').exists()
    assert (destination / 'frontend/server.js').read_text() == '// server'
    assert not (root / 'frontend/node_modules').exists()


def test_cache_copy_is_writable_when_installed_file_is_readonly(bundle, tmp_path):
    root, manifest = bundle
    (root / 'frontend/server.js').chmod(0o444)
    destination = tmp_path / 'cache'
    resources.materialize(root, manifest, destination)
    assert (destination / 'frontend/server.js').stat().st_mode & 0o200
    assert not (root / 'frontend/server.js').stat().st_mode & 0o200


def test_reusing_resources_preserves_prepared_node_dependencies(bundle, tmp_path):
    root, manifest = bundle
    destination = tmp_path / 'cache'
    resources.materialize(root, manifest, destination)
    dependency = destination / 'frontend/node_modules/prepared.txt'
    dependency.parent.mkdir()
    dependency.write_text('already prepared')
    resources.materialize(root, manifest, destination)
    assert dependency.read_text() == 'already prepared'


def test_modified_resources_fail_before_use(bundle, tmp_path):
    root, manifest = bundle
    (root / 'frontend/server.js').write_text('changed')
    with pytest.raises(resources.UIError, match='changed'):
        resources.materialize(root, manifest, tmp_path / 'cache')
    assert not (tmp_path / 'cache').exists()


def test_resource_path_cannot_escape_root(bundle, tmp_path):
    root, manifest = bundle
    sibling = tmp_path / 'outside'
    sibling.write_text('outside')
    manifest['files']['../outside'] = resources.file_digest(sibling)
    with pytest.raises(resources.UIError):
        resources.materialize(root, manifest, tmp_path / 'cache')


def test_parallel_starts_prepare_node_dependencies_once(bundle, tmp_path, monkeypatch):
    root, _manifest = bundle
    monkeypatch.setenv('MS_AGENT_WEBUI_CACHE', str(tmp_path / 'runtime'))
    monkeypatch.setattr(resources, 'check_backend_dependencies', lambda: None)
    common = SimpleNamespace(validate_build=lambda directory: None)
    calls = []

    def install(frontend, production):
        assert production
        calls.append(frontend)
        time.sleep(0.05)
        (frontend / 'node_modules').mkdir()

    def prepare():
        return resources.prepare_installed(root, common, (22, 23, 2),
                                           skip_install=False, install_node=install)

    with ThreadPoolExecutor(max_workers=2) as pool:
        prepared = list(pool.map(lambda _: prepare(), range(2)))
    assert prepared[0] == prepared[1]
    assert len(calls) == 1
    reused = resources.prepare_installed(root, common, (22, 23, 2), skip_install=True,
                                         install_node=lambda *a, **kw: pytest.fail('must not install'))
    assert reused == prepared[0]
    with pytest.raises(resources.UIError, match='need preparation'):
        resources.prepare_installed(root, common, (22, 24, 0), skip_install=True,
                                    install_node=lambda *a, **kw: pytest.fail('must not install'))


def test_missing_backend_dependencies_names_matching_extra(monkeypatch):
    monkeypatch.setattr(resources.importlib.util, 'find_spec', lambda _: None)
    with pytest.raises(resources.UIError, match=r'ms-agent\[webui\]=='):
        resources.check_backend_dependencies()


def test_backend_starts_without_optional_python_notebook_packages(monkeypatch):
    optional = {'ipykernel', 'jupyter_client', 'pyarrow', 'sklearn', 'seaborn'}
    monkeypatch.setattr(resources.importlib.util, 'find_spec',
                        lambda name: None if name in optional else object())
    resources.check_backend_dependencies()


def test_source_wheel_builds_in_cache_once_and_recovers_failed_build(bundle, tmp_path, monkeypatch):
    root, manifest = bundle
    manifest['prebuilt'] = False
    (root / 'RESOURCE-MANIFEST.json').write_text(json.dumps(manifest))
    monkeypatch.setenv('MS_AGENT_WEBUI_CACHE', str(tmp_path / 'runtime'))
    monkeypatch.setattr(resources, 'check_backend_dependencies', lambda: None)
    class BuildError(RuntimeError):
        pass
    def validate(frontend):
        if not (frontend / 'build/ready').is_file():
            raise BuildError('missing build')
    common = SimpleNamespace(validate_build=validate, BuildError=BuildError)
    installs, builds = [], []
    def install(frontend, production):
        assert production is False
        installs.append(frontend)
        (frontend / 'node_modules').mkdir()
    def build(frontend):
        builds.append(frontend)
        if len(builds) == 1:
            raise BuildError('interrupted build')
        (frontend / 'build').mkdir()
        (frontend / 'build/ready').write_text('validated')
    def prepare(skip=False):
        return resources.prepare_installed(root, common, (22, 23, 2),
                                           skip_install=skip, install_node=install, build_frontend=build)
    with pytest.raises(resources.UIError, match='need preparation'):
        prepare(skip=True)
    with pytest.raises(BuildError, match='interrupted'):
        prepare()
    with pytest.raises(resources.UIError, match='need a frontend build'):
        prepare(skip=True)
    prepared = prepare()
    assert prepare(skip=True) == prepared
    assert len(installs) == 1 and len(builds) == 2
    assert not (root / 'frontend/build').exists()
    assert not (root / 'frontend/node_modules').exists()


def test_invalid_prebuilt_wheel_is_not_silently_rebuilt(bundle, tmp_path, monkeypatch):
    root, _ = bundle
    monkeypatch.setenv('MS_AGENT_WEBUI_CACHE', str(tmp_path / 'runtime'))
    monkeypatch.setattr(resources, 'check_backend_dependencies', lambda: None)
    def fail(frontend):
        raise RuntimeError('corrupt release build')
    common = SimpleNamespace(validate_build=fail)
    with pytest.raises(RuntimeError, match='corrupt release'):
        resources.prepare_installed(root, common, (22, 23, 2), skip_install=False,
                                    install_node=lambda *a, **kw: pytest.fail('must not install'),
                                    build_frontend=lambda *a: pytest.fail('must not rebuild'))


@pytest.fixture
def traced(bundle, tmp_path, monkeypatch):
    """A prebuilt cache whose Node preparation can be traced down to its closure."""
    root, _ = bundle
    monkeypatch.setenv('MS_AGENT_WEBUI_CACHE', str(tmp_path / 'runtime'))
    monkeypatch.setattr(resources, 'check_backend_dependencies', lambda: None)
    return SimpleNamespace(
        bundled=root,
        common=SimpleNamespace(validate_build=lambda directory: None),
        cache=tmp_path / 'runtime')


def _install_everything(frontend, production):
    """Stand in for `pnpm install`: a tree carrying a file no closure can reach."""
    modules = frontend / 'node_modules'
    modules.mkdir()
    (modules / 'unreachable.js').write_text('// the 430 MB nobody loads')


def _fake_trace(frontend):
    """Stand in for traceRuntime.ts: assemble build-runtime/ the way it does,
    including pnpm's relative symlink layout, which is what the move must keep."""
    closure = frontend / 'build-runtime/node_modules'
    (closure / '.pnpm/antd@6/node_modules/antd').mkdir(parents=True)
    (closure / '.pnpm/antd@6/node_modules/antd/index.js').write_text('// SSR')
    (closure / 'antd').symlink_to('.pnpm/antd@6/node_modules/antd')
    (frontend / 'build-runtime/server.js').write_text('// entry')


def test_tracing_replaces_the_installed_tree_with_its_closure(traced):
    installs = []

    def install(frontend, production):
        # Tracing imports tsx and @vercel/nft out of this very tree, so it can
        # never be a production install.
        assert production is False
        installs.append(frontend)
        _install_everything(frontend, production)

    prepared = resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                           skip_install=False, install_node=install,
                                           trace_runtime=_fake_trace)
    modules = prepared / 'frontend/node_modules'
    assert len(installs) == 1
    assert not (modules / 'unreachable.js').exists()
    # Moved, not copied: the relative symlink still resolves inside the tree.
    assert (modules / 'antd').is_symlink()
    assert (modules / 'antd/index.js').read_text() == '// SSR'
    assert not (prepared / 'frontend/build-runtime').exists()


def test_traced_cache_is_reused_by_a_plain_start(traced):
    prepared = resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                           skip_install=False, install_node=_install_everything,
                                           trace_runtime=_fake_trace)
    # Exactly what the container does: CMD carries --skip-install and no tracing
    # request, because tracing already happened while the image was built. This
    # start must accept the tree it was shipped, not reject it as unprepared.
    reused = resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                         skip_install=True,
                                         install_node=lambda *a, **kw: pytest.fail('must not install'))
    assert reused == prepared


def test_untraced_cache_is_re_prepared_when_tracing_is_requested(traced):
    resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                skip_install=False, install_node=_install_everything)
    # The reverse of the case above must NOT hold: accepting the full tree here
    # is how the image would quietly go back to shipping 430 MB.
    with pytest.raises(resources.UIError, match='need preparation'):
        resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                    skip_install=True,
                                    install_node=lambda *a, **kw: pytest.fail('must not install'),
                                    trace_runtime=lambda frontend: pytest.fail('must not trace'))


def test_tracing_that_produced_no_closure_keeps_the_installed_tree(traced):
    def trace_without_closure(frontend):
        (frontend / 'build-runtime').mkdir()

    with pytest.raises(resources.UIError, match='no dependency closure'):
        resources.prepare_installed(traced.bundled, traced.common, (22, 23, 2),
                                    skip_install=False, install_node=_install_everything,
                                    trace_runtime=trace_without_closure)
    frontend = next(traced.cache.glob('*/frontend'))
    # Nothing half-pruned, and no stamp claiming this tree is a closure: the next
    # attempt has to find it unprepared rather than serve an incomplete tree.
    assert (frontend / 'node_modules/unreachable.js').exists()
    assert not (frontend / '.node-dependencies.json').exists()
