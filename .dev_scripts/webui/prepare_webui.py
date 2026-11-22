#!/usr/bin/env python3
# Copyright (c) ModelScope Contributors. All rights reserved.
"""Prepare the frontend and exact resource manifest for wheel and sdist."""
import argparse
import os
import shutil
import subprocess
import sys
import webui_packaging as packaging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--skip-build',
        action='store_true',
        help='Reuse a verified, unchanged frontend build')
    parser.add_argument(
        '--sdk-sha', help='Commit to record in release artifacts')
    parser.add_argument(
        '--update-model-catalog',
        action='store_true',
        help='Explicitly refresh models.dev before release preparation; '
        'otherwise validate the fixed offline snapshot')
    args = parser.parse_args()
    catalog_command = [
        sys.executable,
        str(ROOT / '.dev_scripts/update_model_catalog.py')
    ]
    if not args.update_model_catalog:
        catalog_command.append('--check')
    subprocess.run(catalog_command, cwd=ROOT, check=True)
    if not args.skip_build:
        node = shutil.which('node')
        pnpm = shutil.which('pnpm')
        if not node or not pnpm:
            parser.error('Install Node >=22.22.0 and pnpm 10.17.1 first')
        frontend = packaging.WEBUI / 'frontend'
        for command in ([pnpm, 'install',
                         '--frozen-lockfile'], [pnpm, 'build']):
            subprocess.run(
                command,
                cwd=frontend,
                check=True,
                shell=os.name == 'nt' and pnpm.lower().endswith(
                    ('.cmd', '.bat')))
    sha = args.sdk_sha
    if sha is None:
        try:
            sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                          cwd=ROOT,
                                          text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            parser.error(
                'Pass --sdk-sha when preparing a source archive without Git')
    manifest = packaging.write_manifest(sha)
    packaging.validate_release()
    print(
        f'Prepared {len(manifest["files"])} WebUI files for ms-agent {manifest["sdk_version"]}'
    )


if __name__ == '__main__':
    main()
