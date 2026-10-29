# Copyright (c) ModelScope Contributors. All rights reserved.
"""One-line notices for memory writes the user can act on.

TUI's default log level is ERROR, so a warning in the log is invisible.
These sentences are what the session shows instead.
"""
import errno

CHAR_LIMIT_NOTICE = '记忆写不进去：已超过字数上限。请删短 MEMORY.md 后再试。'
DISK_NOTICE = '记忆写不进去：磁盘或权限不允许写入。请检查记忆目录的权限和剩余空间。'
MISSING_DIR_NOTICE = '记忆目录不在了。请确认目录还在，再试一次。'
PERMISSION_NOTICE = '记忆目录没有写入权限。'
NO_SPACE_NOTICE = '磁盘空间不足，记忆写不进去。'
QUIT_WHILE_WRITING = '记忆还在写入，这次退出可能没保存完。请重新打开会话确认 MEMORY.md。'


def disk_notice(exc: BaseException) -> str:
    """Pick the sentence that matches why the write was rejected."""
    err = getattr(exc, 'errno', None)
    if isinstance(exc, FileNotFoundError) or err == errno.ENOENT:
        return MISSING_DIR_NOTICE
    if isinstance(exc, PermissionError) or err in (errno.EACCES, errno.EPERM):
        return PERMISSION_NOTICE
    if err == errno.ENOSPC:
        return NO_SPACE_NOTICE
    return DISK_NOTICE
