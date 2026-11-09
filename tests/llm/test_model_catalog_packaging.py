# Copyright (c) ModelScope Contributors. All rights reserved.
"""Build real wheel/sdist, compare resources, and query an offline installation."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ('models_dev.json', 'models_dev.manifest.json', 'LICENSE')
DENY_NETWORK = """
import socket

def no_network(*args, **kwargs):
    raise AssertionError('catalog build/query attempted network access')

socket.socket.connect = no_network
socket.create_connection = no_network
"""


def run_python(script, *args):
    process = subprocess.run(
        [sys.executable, '-I', '-c', DENY_NETWORK + script, *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert process.returncode == 0, process.stdout + process.stderr
    return process.stdout


@pytest.fixture(scope='module')
def distributions(tmp_path_factory):
    work = tmp_path_factory.mktemp('catalog-packaging')
    egg = work / 'egg'
    egg.mkdir()
    run_python("""
import runpy, sys
setup, egg, build, dist = sys.argv[1:]
sys.argv = [setup, 'egg_info', '--egg-base', egg,
            'build', '--build-base', build,
            'bdist_wheel', '--dist-dir', dist,
            'sdist', '--dist-dir', dist]
runpy.run_path(setup, run_name='__main__')
""", ROOT / 'setup.py', egg, work / 'build', work / 'dist')
    return work


def test_wheel_sdist_ship_identical_verified_resources(distributions):
    wheel = next((distributions / 'dist').glob('*.whl'))
    source = next((distributions / 'dist').glob('*.tar.gz'))
    extracted = distributions / 'source'
    extracted.mkdir()
    with zipfile.ZipFile(wheel) as whl, tarfile.open(source) as sdist:
        prefix = sdist.getnames()[0].split('/')[0]
        for name in RESOURCES:
            relative = 'ms_agent/llm/data/' + name
            original = (ROOT / relative).read_bytes()
            assert whl.read(relative) == original
            assert sdist.extractfile(prefix + '/' + relative).read() == original
        for path in ('ms_agent/llm/model_catalog.py',
                     '.dev_scripts/update_model_catalog.py', 'setup.py'):
            assert prefix + '/' + path in sdist.getnames()
        # Extract only the stdlib validator/update path, not archive symlinks.
        selected = ['ms_agent/llm/model_catalog.py',
                    '.dev_scripts/update_model_catalog.py']
        selected.extend('ms_agent/llm/data/' + name for name in RESOURCES)
        for relative in selected:
            target = extracted / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(sdist.extractfile(prefix + '/' + relative).read())
    output = run_python("""
import runpy, sys
script = sys.argv[1]
sys.argv = [script, '--check']
runpy.run_path(script, run_name='__main__')
""", extracted / '.dev_scripts/update_model_catalog.py')
    manifest = json.loads((ROOT / 'ms_agent/llm/data/models_dev.manifest.json').read_bytes())
    assert f'{manifest["provider_count"]} providers, {manifest["model_count"]} models' in output


def test_installed_wheel_offline_sdk_import(distributions):
    uv = shutil.which('uv')
    if uv is None:
        pytest.skip('uv is needed for an actual offline --no-deps installation')
    wheel = next((distributions / 'dist').glob('*.whl'))
    target = distributions / 'installed'
    env = dict(os.environ, UV_OFFLINE='true', UV_NO_CACHE='true')
    install = subprocess.run(
        [uv, 'pip', 'install', '--python', sys.executable, '--no-deps',
         '--no-index', '--target', str(target), str(wheel)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert install.returncode == 0, install.stdout + install.stderr
    output = run_python("""
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from ms_agent.llm import model_catalog
from ms_agent.llm.spec import get_registry
assert pathlib.Path(sys.argv[1]) in pathlib.Path(model_catalog.__file__).parents
assert model_catalog.get_model('openai', 'gpt-4o')['catalog_provider'] == 'openai'
assert model_catalog.get_provider('minimax')['id'] == 'minimax-cn'
assert len(get_registry().list_providers()) == 19
print(json.dumps(model_catalog.catalog_info()))
""", target)
    info = json.loads(output.strip().splitlines()[-1])
    manifest = json.loads((ROOT / 'ms_agent/llm/data/models_dev.manifest.json').read_bytes())
    assert info == dict(manifest, available=True, location='bundled')


def test_catalog_can_load_without_site_packages():
    script = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('offline_catalog', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module._cache is module._UNSET
assert module.get_model('openai', 'gpt-4o') is not None
assert 'ms_agent.llm.spec' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, '-I', '-S', '-c', DENY_NETWORK + script,
         str(ROOT / 'ms_agent/llm/model_catalog.py')],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_both_build_commands_reject_broken_bundle(monkeypatch):
    from setuptools import Distribution
    spec = importlib.util.spec_from_file_location('_catalog_setup', ROOT / 'setup.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    validation = Mock(side_effect=ValueError('broken catalog'))
    monkeypatch.setattr(setup.model_catalog, 'validate_bundle', validation)
    for command in (setup.build_py, setup.sdist):
        with pytest.raises(ValueError, match='broken catalog'):
            command(Distribution()).run()
    assert validation.call_count == 2


def test_release_preparation_explicit_update_or_offline_check(monkeypatch):
    scripts = ROOT / '.dev_scripts/webui'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('_catalog_prepare', scripts / 'prepare_webui.py')
    prepare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare)
    run = Mock()
    monkeypatch.setattr(prepare.subprocess, 'run', run)
    monkeypatch.setattr(prepare.packaging, 'write_manifest', Mock(return_value={
        'files': [], 'sdk_version': 'test'}))
    monkeypatch.setattr(prepare.packaging, 'validate_release', Mock())
    for flags in ([], ['--update-model-catalog']):
        monkeypatch.setattr(sys, 'argv', ['prepare_webui.py', '--skip-build',
                                        '--sdk-sha', 'test'] + flags)
        prepare.main()
        command = run.call_args.args[0]
        assert command[:2] == [sys.executable, str(ROOT / '.dev_scripts/update_model_catalog.py')]
        assert ('--check' in command) == (not flags)
