# Copyright (c) ModelScope Contributors. All rights reserved.
"""Whole-file writes via a per-writer temp file plus rename.

A reader sees either the whole old file or the whole new one. Writers are not
serialized: the last rename wins, so a caller that needs an atomic
read-modify-write still has to lock.
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Union


def atomic_write_text(path: Union[str, Path],
                      text: str,
                      *,
                      encoding: str = 'utf-8',
                      fsync: bool = False) -> None:
    """Replace what is at ``path`` with ``text`` in one indivisible step.

    Creates the parent directory if it is missing. Set ``fsync`` to flush to
    the device before the rename.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same directory, so the rename cannot cross filesystems; hidden and
    # unique, so scans and watchers ignore it.
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(text)
            if fsync:
                f.flush()
                os.fsync(f.fileno())
        # replace(), not rename(): rename() fails on Windows if path exists.
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_json(path: Union[str, Path],
                      data: Any,
                      *,
                      indent: Union[int, None] = 2,
                      ensure_ascii: bool = False,
                      fsync: bool = False) -> None:
    """:func:`atomic_write_text` for JSON."""
    # Serialized first, so an unencodable value leaves no temp file behind.
    atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=ensure_ascii, indent=indent),
        fsync=fsync)
