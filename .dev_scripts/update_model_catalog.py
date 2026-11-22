#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Sync models.dev for releases; use --check for offline validation."""
import argparse
import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    '_ms_agent_model_catalog', ROOT / 'ms_agent/llm/model_catalog.py')
catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalog)


def download():
    return asyncio.run(catalog.download(timeout=60))


def update(raw, fetched_at, output_dir):
    """Validate before replacing; restore the previous bundle on handled failures."""
    # Keep repository text hooks from changing the bytes after we hash them.
    raw = raw.rstrip(b'\r\n') + b'\n'
    timestamp = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('--fetched-at must include a timezone')
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise ValueError('Output directory must already exist')
    license_bytes = catalog._read(catalog.DATA_DIR / 'LICENSE', 65536)
    manifest = catalog.manifest_for(raw, fetched_at)
    files = (catalog.SNAPSHOT, 'LICENSE', catalog.MANIFEST)
    with tempfile.TemporaryDirectory(
            prefix='.model-catalog-', dir=output_dir.parent) as temporary:
        stage = Path(temporary)
        (stage / catalog.SNAPSHOT).write_bytes(raw)
        (stage / 'LICENSE').write_bytes(license_bytes)
        (stage / catalog.MANIFEST).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        catalog.validate_bundle(stage)
        previous = {}
        for name in files:
            target = output_dir / name
            if target.is_symlink():
                raise ValueError('Refusing symlink catalog resource')
            previous[name] = target.exists()
            if previous[name]:
                shutil.copyfile(target, stage / (name + '.previous'))
        replaced = []
        try:
            for name in files:
                os.replace(stage / name, output_dir / name)
                replaced.append(name)
        except BaseException:
            for name in reversed(replaced):
                if previous[name]:
                    os.replace(stage / (name + '.previous'), output_dir / name)
                else:
                    (output_dir / name).unlink()
            raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--check',
        action='store_true',
        help='Validate fixed resources, without network or writes')
    mode.add_argument(
        '--input',
        type=Path,
        help='Use local upstream JSON instead of the network')
    parser.add_argument(
        '--fetched-at',
        help='Original timezone-aware fetch time; required for --input')
    parser.add_argument('--output-dir', type=Path, default=catalog.DATA_DIR)
    args = parser.parse_args(argv)
    if args.input and not args.fetched_at:
        parser.error(
            '--input requires --fetched-at for reproducible provenance')
    if args.check and args.fetched_at:
        parser.error('--fetched-at cannot be combined with --check')
    try:
        if args.check:
            _, manifest = catalog.validate_bundle(args.output_dir)
        else:
            raw = (
                catalog._read(args.input, catalog.MAX_SNAPSHOT_BYTES)
                if args.input else download())
            fetched_at = args.fetched_at or datetime.now(
                timezone.utc).isoformat()
            manifest = update(raw, fetched_at, args.output_dir)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(
            'Model catalog update/check failed; previous data retained: '
            + str(exc),
            file=sys.stderr)
        return 1
    print(f'Model catalog {manifest["revision"]}: '
          f'{manifest["provider_count"]} providers, '
          f'{manifest["model_count"]} models')
    return 0


if __name__ == '__main__':
    sys.exit(main())
