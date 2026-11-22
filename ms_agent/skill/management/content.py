"""Bounded byte-preserving snapshots, fingerprints and file differences."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .models import FileChange, SkillManagementError

MAX_BYTES = 128 * 1024 * 1024
MAX_FILES = 5000
MAX_TEXT = 256 * 1024
IGNORED = {'.git', '__pycache__', '.DS_Store', '.pytest_cache', '.mypy_cache'}
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|\s]+')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {
    f'{prefix}{i}'
    for prefix in ('COM', 'LPT')
    for i in range(1, 10)
}


def skill_directory_name(value: str) -> str:
    name = _UNSAFE.sub('-', value.strip()).strip('. -').lower()
    name = name.encode()[:128].decode(errors='ignore').strip('. -')
    return name if name and name.upper() not in _RESERVED else 'skill'


def relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or '..' in path.parts or '\\' in value
            or ':' in value or '\x00' in value):
        raise SkillManagementError('INVALID_PACKAGE', 'Invalid package path.')
    return Path(*path.parts)


def manifest(root: Path) -> tuple[str, dict]:
    """Hash paths, byte hashes and executable bits, excluding known caches."""
    if not root.is_dir() or root.is_symlink():
        raise SkillManagementError('CONTENT_MISSING',
                                   'Skill files are missing.')
    entries = {}
    size = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            if name not in IGNORED and (Path(directory) / name).is_symlink():
                raise SkillManagementError(
                    'INVALID_PACKAGE', 'Symbolic links are not supported.')
        dirs[:] = sorted(name for name in dirs if name not in IGNORED)
        for name in sorted(files):
            if name in IGNORED:
                continue
            path = Path(directory) / name
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise SkillManagementError(
                    'INVALID_PACKAGE', 'Only regular files are supported.')
            size += info.st_size
            if size > MAX_BYTES or len(entries) >= MAX_FILES:
                raise SkillManagementError(
                    'PACKAGE_TOO_LARGE', 'The Skill exceeds the size limit.')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(65536), b''):
                    digest.update(block)
            entries[path.relative_to(root).as_posix()] = {
                'sha256': digest.hexdigest(),
                'size': info.st_size,
                'executable': bool(info.st_mode & 0o111),
            }
    payload = json.dumps(entries, sort_keys=True, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(payload.encode()).hexdigest(), entries


def copy_content(source: Path, destination: Path) -> str:
    before, entries = manifest(source)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for name, item in entries.items():
            target = destination / relative_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target, follow_symlinks=False)
            target.chmod(0o755 if item['executable'] else 0o644)
        after, _ = manifest(destination)
        if after != before or manifest(source)[0] != before:
            raise SkillManagementError('PLAN_STALE',
                                       'Content changed. Review again.')
        return after
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def extract_archive(archive: Path, destination: Path) -> Path:
    """Extract one trusted-host download without trusting archive entries."""
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > MAX_FILES or sum(x.file_size
                                               for x in entries) > MAX_BYTES:
                raise SkillManagementError(
                    'PACKAGE_TOO_LARGE', 'The package exceeds the size limit.')
            seen = set()
            written = 0
            for entry in entries:
                rel = relative_path(entry.filename.rstrip('/'))
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (
                        0, stat.S_IFREG, stat.S_IFDIR):
                    raise SkillManagementError('INVALID_PACKAGE',
                                               'Unsupported archive entry.')
                key = rel.as_posix().casefold()
                if key in seen:
                    raise SkillManagementError('INVALID_PACKAGE',
                                               'Duplicate archive path.')
                seen.add(key)
                if any(part in IGNORED for part in rel.parts):
                    continue
                target = destination / rel
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as src, target.open('xb') as dst:
                    for block in iter(lambda: src.read(65536), b''):
                        written += len(block)
                        if written > MAX_BYTES:
                            raise SkillManagementError(
                                'PACKAGE_TOO_LARGE', 'Package is too large.')
                        dst.write(block)
                target.chmod(0o755 if mode & 0o111 else 0o644)
        children = list(destination.iterdir())
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return destination
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise SkillManagementError(
            'INVALID_PACKAGE', 'The archive could not be extracted.') from exc


def text_content(path: Path) -> str | None:
    if not path.exists():
        return ''
    if path.stat().st_size > MAX_TEXT:
        return None
    data = path.read_bytes()
    if b'\0' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def changes(before: Path | None, after: Path) -> list[FileChange]:
    left = manifest(before)[1] if before is not None else {}
    right = manifest(after)[1]
    result = []
    for name in sorted(left.keys() | right.keys()):
        if left.get(name) == right.get(name):
            continue
        kind = 'added' if name not in left else 'removed' if name not in right else 'modified'
        binary = (
            text_content(after / name) is None
            or (before is not None and text_content(before / name) is None))
        result.append(
            FileChange(name, kind,
                       left.get(name, {}).get('size', 0),
                       right.get(name, {}).get('size', 0), binary))
    return result


def file_diff(before: Path | None, after: Path, name: str) -> dict:
    rel = relative_path(name)
    old = text_content(before / rel) if before is not None else ''
    new = text_content(after / rel)
    if old is None or new is None:
        return {'path': name, 'binary': True, 'diff': None, 'truncated': False}
    rows = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile='before/' + name,
            tofile='after/' + name,
            lineterm=''))
    old_path = before / rel if before is not None else None
    new_path = after / rel
    if old_path is not None and old_path.is_file() and new_path.is_file():
        old_exec = bool(old_path.stat().st_mode & 0o111)
        new_exec = bool(new_path.stat().st_mode & 0o111)
        if old_exec != new_exec:
            rows[:0] = [
                'old mode ' + ('100755' if old_exec else '100644'),
                'new mode ' + ('100755' if new_exec else '100644'),
            ]
    return {
        'path': name,
        'binary': False,
        'diff': '\n'.join(rows[:2000]),
        'truncated': len(rows) > 2000
    }
