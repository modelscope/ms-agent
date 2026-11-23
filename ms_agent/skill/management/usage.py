"""Short mutation gates and crash-safe, cross-process leases for Skill readers.

No thread-owned configuration lock is held across an await. Each running turn
owns a separate OS-locked lease file; a process crash releases that lock. The
gate serializes admission with a synchronous filesystem commit.
"""
from __future__ import annotations

import os
import asyncio
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path

from ms_agent.utils.file_lock import file_lock

from .models import SkillManagementError


def _lock(fd):
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _gate(tree: Path) -> Path:
    return tree.parent / 'skill-state' / 'content-gate'


def _readers(tree: Path) -> Path:
    return tree.parent / 'skill-state' / 'readers'


class SkillUseLease:

    def __init__(self, trees):
        self.trees = sorted({Path(p).resolve() for p in trees})
        self.files = []

    def __enter__(self):
        try:
            for tree in self.trees:
                with file_lock(_gate(tree)):
                    readers = _readers(tree)
                    readers.mkdir(parents=True, exist_ok=True)
                    path = readers / (uuid.uuid4().hex + '.lease')
                    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL,
                                 0o600)
                    try:
                        os.write(fd, b'1')
                        _lock(fd)
                    except BaseException:
                        os.close(fd)
                        path.unlink(missing_ok=True)
                        raise
                    self.files.append((path, fd))
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        while self.files:
            path, fd = self.files.pop()
            os.close(fd)
            path.unlink(missing_ok=True)

    def __exit__(self, *args):
        self.close()


@contextmanager
def skill_mutation(tree: Path, *, allow_busy=False):
    """Reject active readers and serialize all cooperating mutations."""
    with file_lock(_gate(tree)):
        readers = _readers(tree)
        for path in readers.glob('*.lease') if readers.exists() else ():
            try:
                fd = os.open(path, os.O_RDWR)
            except FileNotFoundError:
                continue
            stale = False
            try:
                try:
                    _lock(fd)
                except OSError:
                    if not allow_busy:
                        raise SkillManagementError(
                            'SKILL_BUSY',
                            'Task running. Try again later.') from None
                else:
                    # No live owner: a crashed process may have left the path.
                    stale = True
            finally:
                os.close(fd)
            if stale:
                path.unlink(missing_ok=True)
        yield


@contextmanager
def skill_read(trees):
    """Protect short catalog/file reads against the two-rename commit gap."""
    with ExitStack() as stack:
        for tree in sorted({Path(p).resolve() for p in trees}):
            stack.enter_context(file_lock(_gate(tree)))
        yield


class SkillTurnLock(asyncio.Lock):
    """A host's existing turn lock can own the startup-to-completion lease."""

    def __init__(self):
        super().__init__()
        self.skill_lease = None

    def release(self):
        if self.skill_lease is not None:
            self.skill_lease.close()
            self.skill_lease = None
        super().release()
