# Copyright (c) ModelScope Contributors. All rights reserved.
"""Locate WebUI resources and prepare writable caches for installed wheels."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import platform
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class UIError(RuntimeError):
    pass


def find_webui():
    package = Path(__file__).resolve().parents[1]
    bundled = package / 'webui'
    if (bundled / 'RESOURCE-MANIFEST.json').is_file():
        return bundled, True
    checkout = package.parent / 'webui'
    if (package.parent / 'setup.py').is_file() and (
            checkout / 'backend/app/launcher.py').is_file():
        return checkout, False
    raise UIError(
        'WebUI resources are missing. Reinstall the matching ms-agent wheel, '
        'or use a complete SDK source checkout.')


def load_common(webui):
    backend = str(webui / 'backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    return importlib.import_module('app.launcher')


def cache_root():
    override = os.environ.get('MS_AGENT_WEBUI_CACHE')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        base = Path(
            os.environ.get('LOCALAPPDATA',
                           Path.home() / 'AppData/Local'))
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Caches'
    else:
        base = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache'))
    return base / 'ms-agent/webui'


def file_digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def verify_resources(root, manifest):
    if manifest.get('format') != 1 or not manifest.get('files'):
        raise UIError('Invalid WebUI resource manifest; reinstall ms-agent')
    for rel, digest in manifest['files'].items():
        file = root / rel
        if (file.is_symlink() or root.resolve() not in file.resolve().parents
                or not file.is_file() or file_digest(file) != digest):
            raise UIError(f'WebUI resource is missing or changed: {file}')


@contextmanager
def preparation_lock(root, name, timeout=300):
    """Serialize copies/installs; the OS releases the lock if a setup process dies."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ('.' + name + '.lock')).open('a+b') as stream:
        stream.seek(0)
        stream.write(b'0')
        stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise UIError(
                        'Timed out waiting for another WebUI setup process')
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def materialize(bundled, manifest, destination):
    verify_resources(bundled, manifest)
    if destination.exists():
        verify_resources(destination, manifest)
        return
    temporary = Path(
        tempfile.mkdtemp(prefix='.webui-copy-', dir=destination.parent))
    try:
        for rel in list(manifest['files']) + ['RESOURCE-MANIFEST.json']:
            target = temporary / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled / rel, target)
        # Read-only installed files must not make the runtime cache read-only.
        for file in temporary.rglob('*'):
            file.chmod(0o700 if file.is_dir() else 0o600)
        verify_resources(temporary, manifest)
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def node_stamp(frontend, node_version, *, production=True, traced=False):
    """Describe the prepared dependency tree, so a stale one is replaced.

    ``production`` describes the wheel's own mode, not the install that produced
    the tree: tracing needs devDependencies, but that full install is scaffolding
    for the tracer and is gone before this is written. ``traced`` is what tells a
    closure apart from everything ``pnpm install`` resolved.
    """
    return {
        'node':
        list(node_version),
        'platform':
        platform.system(),
        'architecture':
        platform.machine(),
        'lock':
        file_digest(frontend / 'pnpm-lock.yaml'),
        'package_manager':
        json.loads((frontend / 'package.json').read_text())['packageManager'],
        'production':
        production,
        'traced':
        traced,
    }


def _stamp_matches(stamp, expected):
    """Decide whether an already prepared tree satisfies this start.

    Tracing is a property of how the cache was built, not of how it is launched:
    the image traces once while building and the container then starts from a
    plain ``CMD`` that carries no such request. A traced tree therefore answers a
    start that did not ask for one -- otherwise every container start would
    reject the cache it was shipped with. The reverse must not hold: asking for
    tracing when the cache holds the full tree has to re-prepare it, or a
    regression in that step would quietly ship the whole 430 MB again.
    """
    if stamp is None:
        return False
    if stamp.get('traced') and not expected['traced']:
        stamp = {**stamp, 'traced': False}
    return stamp == expected


def _prune_to_traced_closure(frontend):
    """Replace the installed tree with the closure the tracer just verified.

    ``scripts/traceRuntime.ts`` assembles ``build-runtime/`` -- the build output,
    the entries and only the ``node_modules`` files those entries can reach -- and
    boots it to render a page before it returns. That order is the point: the full
    tree is still intact while the closure proves itself, so a dependency the
    tracer could not see fails before anything has been destroyed.
    """
    traced = frontend / 'build-runtime'
    closure = traced / 'node_modules'
    if not closure.is_dir():
        raise UIError('Runtime tracing produced no dependency closure at '
                      + str(closure))
    shutil.rmtree(frontend / 'node_modules')
    # A rename, not a copy: pnpm's layout is relative symlinks into `.pnpm/` and
    # the tracer recreated them as such, so moving the directory keeps every one
    # of them resolving inside it.
    closure.rename(frontend / 'node_modules')
    shutil.rmtree(traced)


def check_backend_dependencies():
    modules = [
        'anthropic', 'exa_py', 'fastapi', 'httpx',
        'loguru', 'mem0', 'pydantic_settings', 'socksio',
        'sse_starlette', 'uvicorn', 'watchfiles'
    ]
    missing = [
        module for module in modules
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        from ms_agent.version import __version__

        raise UIError(
            'Missing WebUI Python dependencies: ' + ', '.join(missing) +
            f'. Run `{sys.executable} -m pip install "ms-agent[webui]=={__version__}"`.'
        )


def prepare_installed(bundled,
                      common,
                      node_version,
                      *,
                      skip_install,
                      install_node,
                      build_frontend=None,
                      trace_runtime=None):
    from ms_agent.version import __version__

    manifest_file = bundled / 'RESOURCE-MANIFEST.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if manifest['sdk_version'] != __version__:
        raise UIError(
            'The WebUI resources do not match the installed SDK version')
    root = cache_root()
    name = __version__ + '-' + file_digest(manifest_file)[:16]
    destination = root / name
    check_backend_dependencies()
    with preparation_lock(root, name):
        materialize(bundled, manifest, destination)
        frontend = destination / 'frontend'
        prebuilt = manifest.get('prebuilt', True)
        if not isinstance(prebuilt, bool):
            raise UIError('Invalid WebUI build mode; reinstall ms-agent')
        if prebuilt:
            common.validate_build(frontend)
        marker = frontend / '.node-dependencies.json'
        expected = node_stamp(
            frontend,
            node_version,
            production=prebuilt,
            traced=bool(trace_runtime))
        try:
            stamp = json.loads(marker.read_text())
        except (OSError, ValueError):
            stamp = None
        ready = _stamp_matches(
            stamp, expected) and (frontend / 'node_modules').is_dir()
        if not ready:
            if skip_install:
                raise UIError(
                    'WebUI Node dependencies need preparation. Run once without --skip-install.'
                )
            marker.unlink(missing_ok=True)
            # The tracer runs out of this tree and imports `tsx` and
            # `@vercel/nft` from it, so tracing cannot start from a production
            # install. What it leaves behind is narrower than either.
            install_node(
                frontend, production=prebuilt and trace_runtime is None)
            if trace_runtime is None:
                marker.write_text(json.dumps(expected, sort_keys=True) + '\n')
        if not prebuilt:
            try:
                common.validate_build(frontend)
            except common.BuildError:
                if skip_install:
                    raise UIError(
                        'WebUI sources need a frontend build. Run once without --skip-install.'
                    ) from None
                if build_frontend is None:
                    raise UIError('No WebUI frontend builder is available')
                build_frontend(frontend)
                common.validate_build(frontend)
        if not ready and trace_runtime is not None:
            # After any build, because the tracer follows what the SSR bundle
            # imports. The stamp lands only once the closure is in place: an
            # interrupted trace must not leave one claiming this tree is traced.
            trace_runtime(frontend)
            _prune_to_traced_closure(frontend)
            marker.write_text(json.dumps(expected, sort_keys=True) + '\n')
    return destination
