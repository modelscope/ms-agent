# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class SkillSourceType(Enum):
    LOCAL_DIR = "local"
    MODELSCOPE = "modelscope"
    GIT = "git"


@dataclass
class SkillSource:
    type: SkillSourceType
    path: Optional[str] = None
    repo_id: Optional[str] = None
    url: Optional[str] = None
    revision: Optional[str] = None
    subdir: Optional[str] = None
    enabled: bool = True


_MODELSCOPE_URI_RE = re.compile(
    r'^modelscope://(?P<repo>[^@#]+)(?:@(?P<rev>[^#]+))?(?:#(?P<sub>.+))?$')

_MODELSCOPE_SKILL_URL_RE = re.compile(
    r'^https?://(?:www\.)?modelscope\.(?:cn|ai)/skills/'
    r'(?P<repo>[^/]+/[^/]+)(?:/.*)?$')

_OWNER_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')

_AT_PREFIX_RE = re.compile(
    r'^@(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)$')


def _looks_like_path(raw: str) -> bool:
    """Return True when *raw* is clearly meant to be a local filesystem path
    rather than a hub identifier (e.g. starts with ``/``, ``./``, ``~``, or
    contains path separators that don't match the ``owner/repo`` pattern).
    """
    return raw.startswith(('/', './', '../', '~'))


def parse_skill_source(raw: str) -> SkillSource:
    """Parse a raw string into a SkillSource.

    Supported formats (checked in order):
      - /abs/path  or  ./rel/path  or  ~/path     -> LOCAL_DIR
      - modelscope://owner/repo[@rev][#subdir]     -> MODELSCOPE
      - https://modelscope.cn/skills/owner/repo    -> MODELSCOPE
      - @owner/repo  (CLI shorthand)               -> MODELSCOPE
      - https://... or git://...                   -> GIT
      - owner/repo  (when path does not exist)     -> MODELSCOPE
      - anything else                              -> LOCAL_DIR
    """
    if _looks_like_path(raw):
        resolved = str(Path(raw).expanduser().resolve())
        return SkillSource(type=SkillSourceType.LOCAL_DIR, path=resolved)

    m = _MODELSCOPE_URI_RE.match(raw)
    if m:
        return SkillSource(
            type=SkillSourceType.MODELSCOPE,
            repo_id=m.group('repo'),
            revision=m.group('rev'),
            subdir=m.group('sub'),
        )

    m = _MODELSCOPE_SKILL_URL_RE.match(raw)
    if m:
        return SkillSource(
            type=SkillSourceType.MODELSCOPE,
            repo_id=m.group('repo'),
        )

    m = _AT_PREFIX_RE.match(raw)
    if m:
        return SkillSource(
            type=SkillSourceType.MODELSCOPE,
            repo_id=m.group('repo'),
        )

    if raw.startswith(('https://', 'http://', 'git://')):
        return SkillSource(type=SkillSourceType.GIT, url=raw)

    if _OWNER_REPO_RE.match(raw) and not os.path.exists(raw):
        return SkillSource(type=SkillSourceType.MODELSCOPE, repo_id=raw)

    resolved = str(Path(raw).resolve()) if not os.path.isabs(raw) else raw
    return SkillSource(type=SkillSourceType.LOCAL_DIR, path=resolved)
