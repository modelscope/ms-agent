#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Deliver verified development wheels using private, runner-local OSS settings."""
import argparse
import configparser
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from development_version import DEVELOPMENT
import publish_webui_release as publish


class OssError(RuntimeError):
    """Only allow non-sensitive status/code information into workflow logs."""
    def __init__(self, operation, status=0, code='OperationFailed'):
        self.status = status
        self.code = code
        super().__init__(f'OSS {operation} failed (HTTP {status}, {code}); check runner configuration')


def error_details(text):
    status = re.search(r'(?:StatusCode|Status Code|status code)[:=\s]+(\d{3})', text)
    allowed = ('NoSuchKey', 'NoSuchBucket', 'NotFound', 'AccessDenied',
               'InvalidAccessKeyId', 'SignatureDoesNotMatch', 'FileAlreadyExists',
               'PreconditionFailed', 'InvalidArgument', 'RequestTimeTooSkewed',
               'ServiceUnavailable', 'InternalError', 'RequestTimeout')
    code = next((value for value in allowed if re.search(r'\b' + value + r'\b', text)),
                'OperationFailed')
    return int(status[1]) if status else 0, code


def sha256(file):
    with file.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class OssStore:
    def __init__(self, root):
        self.root = root.resolve()
        self.config = self.root / 'credentials.ini'
        destination = self.root / 'destination.json'
        for file in (self.config, destination):
            if not file.is_file() or file.is_symlink() or file.stat().st_mode & 0o077:
                raise ValueError('OSS configuration must be private regular files')
        config = configparser.ConfigParser(interpolation=None)
        config.read(self.config)
        profile = config['profile ms-agent']
        if profile.get('mode') != 'AK' or not profile.getboolean('encryptCredential', fallback=False):
            raise ValueError('OSS requires the encrypted runner credential profile')
        self.region = profile['region']
        if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)+', self.region):
            raise ValueError('Invalid OSS region configuration')
        target = json.loads(destination.read_text())
        uri = urllib.parse.urlsplit(target['uri'])
        if (uri.scheme != 'oss' or uri.query or uri.fragment
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', uri.netloc)
                or not uri.path.strip('/') or any(p in ('.', '..') for p in uri.path.split('/'))):
            raise ValueError('Invalid OSS destination configuration')
        self.bucket = uri.netloc
        self.prefix = uri.path.strip('/') + '/'
        regional_endpoint = f'https://oss-{self.region}.aliyuncs.com'
        self.endpoint = target.get('endpoint', regional_endpoint)
        if self.endpoint not in (
                regional_endpoint, 'https://oss-accelerate.aliyuncs.com',
                'https://oss-accelerate-overseas.aliyuncs.com'):
            raise ValueError('OSS endpoint must be the regional or transfer acceleration HTTPS endpoint')
        self.binary = self.root / 'bin/ossutil'
        self.state = self.root / 'deliveries'
        self.state.mkdir(mode=0o700, exist_ok=True)
        if self.state.is_symlink() or self.state.stat().st_mode & 0o077:
            raise ValueError('OSS delivery records must use a private directory')

    def key(self, relative):
        if (not relative or '\\' in relative or relative.startswith('/')
                or any(p in ('', '.', '..') for p in relative.split('/'))):
            raise ValueError('Invalid relative delivery path')
        return self.prefix + relative

    def url(self, relative):
        return (f'https://{self.bucket}.oss-{self.region}.aliyuncs.com/'
                + urllib.parse.quote(self.key(relative), safe='/'))

    def _run(self, operation, arguments):
        command = [str(self.binary), *arguments, '--config-file', str(self.config),
                   '--profile', 'ms-agent', '--region', self.region,
                   '--endpoint', self.endpoint,
                   '--ignore-env-var', '--loglevel', 'off', '--retry-times', '2',
                   '--read-timeout', '60']
        # Large wheels cross regions; metadata requests should still fail promptly.
        timeout = 600 if operation in ('put-object', 'upload', 'download') else 120
        for attempt in range(3):
            try:
                result = subprocess.run(command, cwd=self.state, capture_output=True,
                                        text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                status, code = 0, 'RequestTimeout'
            else:
                if result.returncode == 0:
                    return result.stdout
                status, code = error_details(result.stdout + '\n' + result.stderr)
            if attempt < 2 and (status in (408, 429, 500, 502, 503, 504)
                                or (status == 0 and code in ('RequestTimeout', 'OperationFailed'))):
                time.sleep(2 ** attempt)
                continue
            raise OssError(operation, status, code) from None

    def api(self, operation, relative, *arguments):
        output = self._run(operation, ['api', operation, '--bucket', self.bucket,
                           '--key', self.key(relative), '--output-format', 'json', *arguments])
        try:
            # ossutil may append elapsed-time text after the JSON result.
            return json.JSONDecoder().raw_decode(output.lstrip())[0]
        except ValueError:
            raise OssError(operation, code='InvalidResponse') from None

    def exists(self, relative):
        try:
            self.api('head-object', relative)
            return True
        except OssError as exc:
            if exc.status == 404 and exc.code in ('NoSuchKey', 'NotFound'):
                return False
            raise

    def download(self, relative, file):
        self._run('download', ['cp', 'oss://' + self.bucket + '/' + self.key(relative),
                              str(file.resolve()), '--force', '--no-progress',
                              '--bigfile-threshold', '4Mi', '--part-size', '1Mi',
                              '--parallel', '16', '--no-error-report'])

    def matches(self, relative, expected):
        with tempfile.TemporaryDirectory(prefix='.verify-', dir=self.state) as temporary:
            file = Path(temporary) / 'object'
            self.download(relative, file)
            return sha256(file) == expected

    def put(self, relative, file, *, public=False, immutable=True):
        if file.stat().st_size >= 4 * 1024 * 1024 and immutable:
            return self.put_large(relative, file, public=public)
        # ossutil requires '=' for boolean values; a bare flag is treated as true.
        self.api('put-object', relative, '--body', 'file://' + str(file.resolve()),
                 '--object-acl', 'public-read' if public else 'private',
                 f'--forbid-overwrite={str(immutable).lower()}',
                 '--cache-control', 'public, max-age=31536000, immutable' if public else 'no-store')

    def put_large(self, relative, file, *, public):
        # cp supports resumable parallel transfers, but has no atomic no-overwrite
        # switch. Stage privately, then let OSS copy with that protection enabled.
        if file.stat().st_size > 1024 ** 3:
            raise ValueError('Wheel exceeds the 1 GiB server-side copy limit')
        identity = sha256(file)
        staging = f'staging/{identity}/{file.name}'
        checkpoint = self.state / 'checkpoints' / identity
        with self.locked():
            checkpoint.mkdir(parents=True, mode=0o700, exist_ok=True)
            self._run('upload', ['cp', str(file.resolve()),
                                'oss://' + self.bucket + '/' + self.key(staging),
                                '--acl', 'private', '--force', '--no-progress',
                                '--no-error-report', '--bigfile-threshold', '4Mi',
                                '--part-size', '1Mi', '--parallel', '16',
                                '--checkpoint-dir', str(checkpoint),
                                '--cache-control', 'public, max-age=31536000, immutable'
                                if public else 'no-store'])
            # Check the staged bytes before making the final object public.
            if not self.matches(staging, identity):
                raise ValueError('Staged OSS upload differs from the validated wheel')
            try:
                self.api('copy-object', relative, '--copy-source',
                         urllib.parse.quote('/' + self.bucket + '/' + self.key(staging), safe='/'),
                         '--object-acl', 'public-read' if public else 'private',
                         '--forbid-overwrite=true')
            finally:
                self.api('delete-object', staging)
                shutil.rmtree(checkpoint, ignore_errors=True)

    def ensure_object(self, relative, file, *, public=False):
        expected = sha256(file)
        if not self.exists(relative):
            try:
                self.put(relative, file, public=public)
            except OssError as exc:
                # A timed-out upload or concurrent identical writer may have finished.
                if exc.code != 'FileAlreadyExists':
                    raise
        if not self.matches(relative, expected):
            raise ValueError('Existing OSS object differs from the validated artifact; refusing overwrite')
        acl = self.api('get-object-acl', relative).get('AccessControlList', {}).get('Grant')
        expected_acl = 'public-read' if public else 'private'
        if acl != expected_acl:
            self.api('put-object-acl', relative, '--object-acl', expected_acl)
        if public:
            self.verify_anonymous(relative, expected)

    def verify_anonymous(self, relative, expected):
        url = self.url(relative)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(3):
            try:
                with opener.open(url, timeout=60) as response:
                    if response.status != 200 or response.geturl() != url:
                        raise OssError('anonymous-download', code='UnexpectedResponse')
                    checksum = hashlib.file_digest(response, 'sha256').hexdigest()
            except urllib.error.HTTPError as exc:
                if attempt == 2 or exc.code not in (408, 429, 500, 502, 503, 504):
                    raise OssError('anonymous-download', exc.code) from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if isinstance(getattr(exc, 'reason', None), ssl.SSLCertVerificationError):
                    raise OssError('anonymous-download', code='CertificateVerifyFailed') from None
                if attempt == 2:
                    raise OssError('anonymous-download', code='ConnectionFailed') from None
            else:
                if checksum != expected:
                    raise ValueError('Anonymous OSS download differs from the validated wheel')
                return
            time.sleep(2 ** attempt)

    def read_json(self, relative):
        if not self.exists(relative):
            return None
        with tempfile.TemporaryDirectory(prefix='.read-', dir=self.state) as temporary:
            file = Path(temporary) / 'record.json'
            self.download(relative, file)
            try:
                return json.loads(file.read_text())
            except ValueError:
                raise ValueError('Existing OSS delivery record is invalid') from None

    @contextlib.contextmanager
    def locked(self):
        with (self.state / '.publish.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def local_record(self, filename, record):
        with tempfile.NamedTemporaryFile(mode='w', dir=self.state, delete=False) as output:
            json.dump(record, output, indent=2)
            output.write('\n')
            temporary = Path(output.name)
        temporary.chmod(0o600)
        os.replace(temporary, self.state / filename)


def wheel_input(directory):
    release = publish.load_inputs(directory)
    match = DEVELOPMENT.fullmatch(release['version'])
    if not match or not re.fullmatch(r'[0-9a-f]{40}', release['sdk_commit']):
        raise ValueError('OSS business delivery requires a development build and full source commit')
    wheels = [name for name in release['files'] if name.endswith('.whl')]
    if len(wheels) != 1 or wheels[0] != f'ms_agent-{release["version"]}-py3-none-any.whl':
        raise ValueError('Expected the single versioned MS-Agent wheel from this build')
    return release, directory / wheels[0], int(match[4])


def upload_wheel(store, directory):
    release, wheel, build_id = wheel_input(directory)
    relative = f'builds/{release["version"]}/{wheel.name}'
    store.ensure_object(relative, wheel, public=True)
    receipt = {'format': 1, 'version': release['version'], 'build_id': build_id,
               'sdk_commit': release['sdk_commit'], 'wheel': wheel.name,
               'wheel_sha256': release['files'][wheel.name], 'wheel_url': store.url(relative)}
    store.local_record(release['version'] + '.wheel.json', receipt)
    print('Development wheel uploaded and anonymous download verified: ' + release['version'])
    return receipt


def complete_delivery(store, directory, image_record, image_receipt):
    release, wheel, build_id = wheel_input(directory)
    image = publish.image_metadata(release, image_record)
    receipt = json.loads(image_receipt.read_text())
    expected = {'version': release['version'], 'sdk_commit': release['sdk_commit'],
                'wheel_sha256': release['files'][wheel.name], 'image_id': image['image_id'],
                'image': publish.REGISTRY_IMAGE + ':' + release['version']}
    if any(receipt.get(key) != value for key, value in expected.items()) or not re.fullmatch(
            re.escape(publish.REGISTRY_IMAGE) + r'@sha256:[0-9a-f]{64}', receipt.get('image_digest', '')):
        raise ValueError('ACR receipt does not match the validated development wheel/image')
    # Recheck wheel access before making a matching pair discoverable.
    record = dict(upload_wheel(store, directory), image=receipt['image'],
                  image_digest=receipt['image_digest'], image_id=image['image_id'])
    with store.locked():
        with tempfile.TemporaryDirectory(prefix='.complete-', dir=store.state) as temporary:
            file = Path(temporary) / 'manifest.json'
            file.write_text(json.dumps(record, indent=2) + '\n')
            store.ensure_object(f'builds/{release["version"]}/manifest.json', file)
            current = store.read_json('channels/dev/latest.json')
            if current:
                version = DEVELOPMENT.fullmatch(str(current.get('version', '')))
                if not version or current.get('build_id') != int(version[4]):
                    raise ValueError('Existing latest delivery record has an invalid build identity')
                if current['build_id'] == build_id and current != record:
                    raise ValueError('This build ID already identifies a different completed delivery')
            if not current or current['build_id'] < build_id:
                store.put('channels/dev/latest.json', file, immutable=False)
                if not store.matches('channels/dev/latest.json', sha256(file)):
                    raise ValueError('Latest delivery verification failed')
                current = record
            store.local_record('latest.json', current)
            store.local_record(release['version'] + '.json', record)
    print('Matching development wheel/image delivery completed: ' + release['version'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['upload', 'complete'])
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--image-record', type=Path)
    parser.add_argument('--image-receipt', type=Path)
    parser.add_argument('--config-root', type=Path,
                        default=os.environ.get('MS_AGENT_OSS_ROOT') or None,
                        help='Private configuration directory; defaults to MS_AGENT_OSS_ROOT')
    args = parser.parse_args()
    if args.config_root is None:
        parser.error('Set MS_AGENT_OSS_ROOT or pass --config-root')
    if not args.config_root.is_absolute():
        parser.error('MS_AGENT_OSS_ROOT / --config-root must be an absolute directory')
    if args.action == 'complete' and (not args.image_record or not args.image_receipt):
        parser.error('complete requires the validated image record and ACR receipt')
    os.umask(0o077)
    try:
        store = OssStore(args.config_root)
        if args.action == 'upload':
            upload_wheel(store, args.inputs.resolve())
        else:
            complete_delivery(store, args.inputs.resolve(), args.image_record, args.image_receipt)
    except OssError as exc:
        parser.exit(1, str(exc) + '\n')
    except Exception:
        # Do not print subprocess arguments, response bodies, local configuration
        # or arbitrary exception messages: they can contain the private address.
        parser.exit(1, 'OSS delivery failed validation; inspect runner-local inputs and configuration.\n')


if __name__ == '__main__':
    main()
