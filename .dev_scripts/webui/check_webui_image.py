#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Check a built image locally without contacting a registry or a model."""
import argparse
import json
import subprocess
import uuid
import webui_smoke as smoke
from pathlib import Path


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def check_package_installation(name):
    """Install a local wheel through the agent's PATH, then import it in Python."""
    code = r'''
import configparser
import asyncio
import importlib.metadata
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path
from omegaconf import OmegaConf
from ms_agent.tools.code.local_code_executor import LocalCodeExecutionTool

prefix = Path(sys.prefix)
assert prefix != Path(sys.base_prefix), 'SDK must run in its image environment'
before = sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())
parent_path = os.environ['PATH']

config = configparser.ConfigParser()
config.read('/etc/pip.conf')
index = config['global']['index-url']
assert index.startswith('https://')
uv_config = tomllib.loads(Path('/etc/uv/uv.toml').read_text())
assert [item['url'] for item in uv_config['index'] if item.get('default')] == [index]

package = 'ms-agent-install-probe'
module = '_ms_agent_install_probe'
assert importlib.util.find_spec(module) is None
with tempfile.TemporaryDirectory() as temporary:
    tool = LocalCodeExecutionTool(OmegaConf.create({
        'output_dir': temporary,
        'tools': {'code_executor': {'include': ['shell_executor']}},
    }))
    shell_env = tool.shell_env
    python = shutil.which('python', path=shell_env['PATH'])
    pip = shutil.which('pip', path=shell_env['PATH'])
    assert python == '/usr/local/bin/python', python
    assert pip == '/usr/local/bin/pip', pip
    assert str(prefix / 'bin') not in shell_env['PATH'].split(os.pathsep)
    assert subprocess.check_output(['pip', 'config', '--global', 'get', 'global.index-url'], env=shell_env, text=True).strip() == index
    subprocess.run([python, '-c', 'import requests, yaml, bs4; import sys; '
                    'assert sys.prefix == sys.base_prefix'],
                   env=shell_env, check=True, timeout=30)
    async def shell(command):
        await tool.connect()
        try:
            assert not hasattr(tool, 'kernel_session'), 'Local tool must not create a Jupyter kernel'
            result = json.loads(await tool.shell_executor(command))
            assert result['success'], result
        finally:
            await tool.cleanup()
    wheel = Path(temporary) / 'ms_agent_install_probe-0.0.0-py3-none-any.whl'
    info = 'ms_agent_install_probe-0.0.0.dist-info/'
    files = {
        module + '.py': 'VALUE = "installed"\n',
        info + 'METADATA': 'Metadata-Version: 2.1\nName: ms-agent-install-probe\nVersion: 0.0.0\n',
        info + 'WHEEL': 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    files[info + 'RECORD'] = ''.join(path + ',,\n' for path in [*files, info + 'RECORD'])
    with zipfile.ZipFile(wheel, 'w') as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    try:
        probe = ('import _ms_agent_install_probe as p; '
                 'from pathlib import Path; import sys; '
                 'assert p.VALUE == "installed"; '
                 'assert sys.prefix == sys.base_prefix; '
                 'assert Path(p.__file__).is_relative_to(Path(sys.prefix))')
        asyncio.run(shell('pip install --no-index --no-deps ' + shlex.quote(str(wheel))
                          + ' && python -c ' + shlex.quote(probe)))
        assert importlib.util.find_spec(module) is None, 'Task package leaked into service Python'
        assert before == sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())
        assert os.environ['PATH'] == parent_path
    finally:
        subprocess.run(['pip', 'uninstall', '--yes', '--disable-pip-version-check', package],
                       env=shell_env, check=True, timeout=30)
print('Agent package installation, service isolation and index configuration passed')
'''
    subprocess.run(['docker', 'exec', name, 'python', '-c', code],
                   check=True,
                   timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='ms-agent-webui:validated')
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--logs', type=Path, required=True)
    parser.add_argument('--resource-label', default='')
    args = parser.parse_args()
    args.logs.mkdir(parents=True, exist_ok=True)
    release = json.loads((args.inputs / 'release.json').read_text())
    image = json.loads(docker('image', 'inspect', args.image))[0]
    wheel_sha = next(value for name, value in release['files'].items()
                     if name.endswith('.whl'))
    labels = image['Config']['Labels']
    assert image['Architecture'] == 'amd64'
    assert labels['org.opencontainers.image.revision'] == release['sdk_commit']
    assert labels['org.opencontainers.image.version'] == release['version']
    assert labels['com.modelscope.ms-agent.wheel-sha256'] == wheel_sha
    name = 'ms-agent-smoke-' + uuid.uuid4().hex[:12]
    volume = name + '-data'
    label_args = ['--label', args.resource_label
                  ] if args.resource_label else []
    docker('volume', 'create', *label_args, volume)
    state = None
    try:
        for scenario in ('normal', 'restart', 'backend', 'frontend'):
            docker('run', *label_args, '--cpus', '2', '--memory', '4g',
                   '--detach', '--name', name, '--publish', '127.0.0.1::8000',
                   '--mount', 'type=volume,source=' + volume + ',target=/data',
                   args.image)
            try:
                mapping = docker('port', name, '8000/tcp')
                base = 'http://' + mapping
                smoke.ready(base)
                if scenario == 'normal':
                    check_package_installation(name)
                installed = json.loads(
                    docker(
                        'exec', name, 'python', '-c',
                        'import ms_agent.agent_hub; '
                        'import bs4, lxml; '
                        'from ms_agent.cli.ui_resources import find_webui; '
                        'p, installed = find_webui(); assert installed; '
                        'print((p / "RESOURCE-MANIFEST.json").read_text())'))
                assert installed['sdk_commit'] == release['sdk_commit']
                assert installed['sdk_version'] == release['version']
                if scenario == 'normal':
                    state = smoke.create(base)
                elif scenario == 'restart':
                    smoke.verify(base, state)
                    smoke.cleanup(base, state)
                if scenario in ('backend', 'frontend'):
                    # The marker is an argument, not interpolated shell code.
                    code = '''import os, signal, sys
from pathlib import Path
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        args = (proc / 'cmdline').read_bytes().split(b'\\0')
        backend = len(args) > 2 and args[1] == b'-c' and args[2].startswith(b'from app.launcher import _run_api;')
        frontend = len(args) > 1 and args[0].endswith(b'node') and args[1].endswith(b'/server.js')
        if (backend and sys.argv[1] == 'backend') or (frontend and sys.argv[1] == 'frontend'):
            os.kill(int(proc.name), signal.SIGKILL)
            break
    except (FileNotFoundError, ProcessLookupError):
        continue
else:
    raise SystemExit('Expected service process was not found')
'''
                    docker('exec', name, 'python', '-c', code, scenario)
                    # Bound the failure wait, so a broken supervisor fails CI.
                    exit_code = subprocess.check_output(
                        ['docker', 'wait', name], text=True,
                        timeout=30).strip()
                    assert exit_code != '0'
                else:
                    docker('stop', '--time', '20', name)
                    assert docker('inspect', '--format', '{{.State.ExitCode}}',
                                  name) == '0'
            finally:
                (args.logs /
                 (scenario + '.log')).write_text(docker('logs', name))
                subprocess.run(['docker', 'rm', '--force', name], check=False)
        record = {
            **release, 'image_id': image['Id'],
            'image': args.image,
            'wheel_sha256': wheel_sha,
            'smoke': 'passed'
        }
        args.output.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, indent=2))
    finally:
        subprocess.run(['docker', 'rm', '--force', name],
                       check=False,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        subprocess.run(['docker', 'volume', 'rm', volume], check=True)


if __name__ == '__main__':
    main()
