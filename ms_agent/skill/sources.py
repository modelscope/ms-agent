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
_OWNER_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def parse_skill_source(raw: str) -> SkillSource:
    """Parse a raw string into a SkillSource.

    Supported formats:
      - /abs/path/to/skills           -> LOCAL_DIR
      - ./relative/path               -> LOCAL_DIR
      - modelscope://owner/repo@rev   -> MODELSCOPE
      - https://... or git://...      -> GIT
      - owner/repo                    -> MODELSCOPE (when path does not exist)
    """
    if os.path.exists(raw):
        return SkillSource(type=SkillSourceType.LOCAL_DIR, path=raw)

    m = _MODELSCOPE_URI_RE.match(raw)
    if m:
        return SkillSource(
            type=SkillSourceType.MODELSCOPE,
            repo_id=m.group('repo'),
            revision=m.group('rev'),
            subdir=m.group('sub'),
        )

    if raw.startswith(('https://', 'http://', 'git://')):
        return SkillSource(type=SkillSourceType.GIT, url=raw)

    if _OWNER_REPO_RE.match(raw):
        return SkillSource(type=SkillSourceType.MODELSCOPE, repo_id=raw)

    return SkillSource(type=SkillSourceType.LOCAL_DIR, path=raw)
