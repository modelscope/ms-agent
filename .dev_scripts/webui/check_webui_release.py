#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Validate release versions/resources and record the exact package inputs."""
import argparse
import email
import hashlib
import json
import re
import tarfile
import tomllib
import webui_packaging as packaging
import zipfile
from pathlib import Path
from development_version import DEVELOPMENT

ROOT = Path(__file__).resolve().parents[2]


def check_tag(version, tag):
    if DEVELOPMENT.fullmatch(version):
        if tag:
            raise ValueError('Development packages must not use release tags')
        return
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:rc\d+)?', version):
        raise ValueError('Expected X.Y.Z or X.Y.ZrcN, got ' + version)
    if tag and tag != 'v' + version:
        raise ValueError(f'Tag {tag} does not match SDK version {version}')


def dependency_key(value):
    return re.sub(r'\s+', '', value).lower().replace('_', '-')


def check_source(tag=None):
    version = packaging.version()
    check_tag(version, tag)
    backend = ROOT / 'webui/backend'
    project = tomllib.loads((backend / 'pyproject.toml').read_text())
    dependencies = {
        dependency_key(d)
        for d in project['project']['dependencies']
        if dependency_key(d) != 'ms-agent'
    }
    extra = {
        dependency_key(line)
        for line in (ROOT / 'requirements/webui.txt').read_text().splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }
    if dependencies != extra:
        raise ValueError(
            'requirements/webui.txt differs from backend dependencies: '
            + str(sorted(dependencies ^ extra)))
    lock = tomllib.loads((backend / 'uv.lock').read_text())
    sdk = [p for p in lock['package'] if p['name'] == 'ms-agent']
    if (len(sdk) != 1 or sdk[0]['version'] != version
            or set(sdk[0]['source']) != {'editable'}
            or Path(sdk[0]['source']['editable']) != Path('../..')):
        raise ValueError('Update the embedded SDK version/path in uv.lock')
    return version, dependencies


def forbidden(path):
    parts = Path(path).parts
    return any(
        part in {
            '.env', '.agents', '.claude', 'node_modules', '__pycache__',
            '.venv', 'CLAUDE.md', 'skills-lock.json'
        } for part in parts)


def check_artifacts(directory, version, dependencies, sdk_sha):
    wheels = list(directory.glob('*.whl'))
    archives = list(directory.glob('*.tar.gz'))
    if len(wheels) != 1 or len(archives) != 1:
        raise ValueError('Expected exactly one wheel and one sdist')
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        if any(forbidden(name) for name in names):
            raise ValueError('Unexpected local/development files in wheel')
        metadata = email.message_from_bytes(
            wheel.read(
                next(
                    name for name in names
                    if name.endswith('.dist-info/METADATA'))))
        if metadata['Version'] != version:
            raise ValueError('Wheel version mismatch')
        declared = {
            dependency_key(req.split(';')[0])
            for req in metadata.get_all('Requires-Dist', [])
            if re.search(r'extra\s*==\s*[\"\x27]webui[\"\x27]', req)
        }
        if declared != dependencies:
            raise ValueError('Wheel webui extra lost requirements: '
                             + str(sorted(declared ^ dependencies)))
        prefix = 'ms_agent/webui/'
        manifest = json.loads(wheel.read(prefix + 'RESOURCE-MANIFEST.json'))
        if (manifest.get('prebuilt', True) is not True
                or 'frontend/build/webui-build.json' not in manifest['files']):
            raise ValueError('Published packages require prebuilt WebUI resources')
        if manifest['sdk_version'] != version or manifest[
                'sdk_commit'] != sdk_sha:
            raise ValueError(
                'Wheel provenance does not match this release commit')
        for rel, expected in manifest['files'].items():
            if hashlib.sha256(
                    wheel.read(prefix + rel)).hexdigest() != expected:
                raise ValueError('Changed wheel resource: ' + rel)
        with tarfile.open(archives[0]) as archive:
            members = archive.getnames()
            top = members[0].split('/')[0] + '/webui/'
            if any(forbidden(name) for name in members):
                raise ValueError('Unexpected local/development files in sdist')
            for rel, expected in manifest['files'].items():
                if hashlib.sha256(archive.extractfile(
                        top + rel).read()).hexdigest() != expected:
                    raise ValueError('sdist and wheel resources differ: '
                                     + rel)
    runtime = directory / 'runtime-requirements.txt'
    text = runtime.read_text()
    # The image installs the wheel separately. Never export an editable path,
    # another SDK distribution or a Git checkout into its dependency layer.
    if re.search(r'(?m)^(?:-e |ms[-_]agent[ =@]|\.?\.?/|https?://|git\+)',
                 text):
        raise ValueError(
            'Runtime dependency export includes a source/SDK install')
    shell = directory / 'shell-requirements.txt'
    if not shell.is_file():
        raise ValueError('Missing shell-requirements.txt in image inputs')
    if shell.read_bytes() != (ROOT / 'docker/webui-shell.txt').read_bytes():
        raise ValueError('Shell dependency lock differs from the source')
    inputs = wheels + archives + [runtime, shell]
    info = {
        'format': 1,
        'version': version,
        'sdk_commit': sdk_sha,
        'files': {file.name: packaging.digest(file)
                  for file in inputs}
    }
    output = directory / 'release.json'
    output.write_text(json.dumps(info, indent=2) + '\n')
    checksums = {**info['files'], output.name: packaging.digest(output)}
    (directory / 'SHA256SUMS').write_text(''.join(
        digest + '  ' + name + '\n' for name, digest in checksums.items()))
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag')
    parser.add_argument('--dist', type=Path)
    parser.add_argument('--sdk-sha')
    parser.add_argument('--package-version', default='',
                        help='Expected development version built from this source')
    args = parser.parse_args()
    version, dependencies = check_source(args.tag)
    if args.package_version:
        if args.tag or not DEVELOPMENT.fullmatch(args.package_version):
            parser.error('--package-version is only for untagged development packages')
        version = args.package_version
    if args.dist:
        if not args.sdk_sha or not re.fullmatch(r'[0-9a-f]{40}', args.sdk_sha):
            parser.error('--dist requires a full --sdk-sha')
        info = check_artifacts(args.dist, version, dependencies, args.sdk_sha)
        print(json.dumps(info, indent=2))
    else:
        print('Source version and WebUI dependencies agree: ' + version)


if __name__ == '__main__':
    main()
