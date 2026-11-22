"""Reentrant locks for cooperating threads and local processes."""
from __future__ import annotations

import errno
import hashlib
import os
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

_guard = threading.Lock()
_locks = {}
_held = threading.local()
_open_fds = set()


def _after_fork():
    global _guard, _locks, _held, _open_fds
    for fd in _open_fds:
        os.close(fd)
    _open_fds = set()
    _guard = threading.Lock()
    _locks = {}
    _held = threading.local()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


@contextmanager
def file_lock(resource: str | Path, timeout: float = 10):
    """Lock a stable sidecar, not the inode replaced by an atomic write.

    Callers locking multiple resources must use a consistent order. Lock files
    stay in place on release; deleting them would split cooperating writers.
    """
    path = Path(resource).expanduser().resolve()
    key = os.path.normcase(str(path))
    with _guard:
        lock = _locks.setdefault(key, threading.RLock())
    deadline = time.monotonic() + timeout
    if not lock.acquire(timeout=max(0, timeout)):
        raise TimeoutError(f'Timed out locking {path.name}')
    held = getattr(_held, 'resources', None)
    if held is None:
        held = _held.resources = set()
    try:
        if key in held:
            yield
            return
        lock_dir = path.parent / '.locks'
        lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = lock_dir / (hashlib.sha256(key.encode()).hexdigest() + '.lock')
        with _guard:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            _open_fds.add(fd)
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'\0')
                os.lseek(fd, 0, os.SEEK_SET)
                acquire = lambda: msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                release = lambda: msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                acquire = lambda: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                release = lambda: fcntl.flock(fd, fcntl.LOCK_UN)
            while True:
                try:
                    acquire()
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'Timed out locking {path.name}') from None
                    time.sleep(min(0.02, max(0, deadline - time.monotonic())))
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                release()
        finally:
            with _guard:
                _open_fds.remove(fd)
                os.close(fd)
    finally:
        lock.release()


def locked(resource):
    """Protect a complete synchronous operation; resolve its resource per call."""
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with file_lock(resource(*args, **kwargs)):
                return function(*args, **kwargs)
        return wrapped
    return decorate
