"""Interface-independent contracts for managed Skill installations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Optional


class SkillManagementError(Exception):
    """A stable error code, safe message, and optional retry information."""

    def __init__(self,
                 code: str,
                 message: str,
                 retry_after: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after

    def to_dict(self):
        return {
            'code': self.code,
            'message': str(self),
            'retry_after': self.retry_after
        }


@dataclass(frozen=True)
class SkillScope:
    """None denotes global; project paths are resolved by the calling host."""

    project_path: Optional[str] = None

    def __post_init__(self):
        if self.project_path is not None:
            object.__setattr__(
                self, 'project_path',
                str(Path(self.project_path).expanduser().resolve()))


@dataclass(frozen=True)
class ManagedSource:
    provider: str
    repository: str
    ref: str
    revision: str
    selector_kind: str = 'branch'
    subdir: str = ''
    url: str = ''
    registry_id: Optional[str] = None

    def __post_init__(self):
        if (self.provider not in ('github', 'modelscope') or not re.fullmatch(
                r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', self.repository)
                or any(p in ('.', '..') for p in self.repository.split('/'))
                or not re.fullmatch(r'[0-9a-f]{40}', self.revision)
                or self.selector_kind not in ('branch', 'tag', 'commit')
                or not self.ref or len(self.ref) > 256
                or Path(self.subdir).is_absolute()
                or '..' in Path(self.subdir).parts or '\\' in self.subdir
                or ':' in self.subdir
                or (self.registry_id is not None and
                    (self.provider != 'modelscope' or self.registry_id not in
                     (self.repository, '@' + self.repository)))):
            raise SkillManagementError('INVALID_PACKAGE',
                                       'Invalid Skill source identity.')

    @property
    def identity(self):
        # Records created before registry_id existed only used mirrored IDs.
        return (self.provider, (self.registry_id or '@' + self.repository)
                if self.provider == 'modelscope' else self.repository)

    def to_dict(self):
        return asdict(self)


@dataclass
class SourceCollection:
    """A discovery entry, never an installed Skill's update source."""

    repository: str
    url: str
    title: str
    members: list[str]
    provider: str = 'modelscope'
    kind: str = 'collection'


@dataclass
class SourceCandidate:
    id: str
    name: str
    description: str
    subdir: str
    runtime_skill_id: str
    version_label: Optional[str] = None
    conflict: Optional[str] = None
    source: Optional[ManagedSource] = None
    source_label: Optional[str] = None
    error: Optional[dict] = None


@dataclass
class SourcePreview:
    id: str
    scope: SkillScope
    source: ManagedSource | SourceCollection
    candidates: list[SourceCandidate]
    expires_at: str


@dataclass
class FileChange:
    path: str
    kind: str
    old_size: int = 0
    new_size: int = 0
    binary: bool = False


@dataclass
class PlanItem:
    id: str
    runtime_skill_id: str
    name: str
    source: ManagedSource
    candidate_digest: str
    local_digest: Optional[str]
    installation_id: Optional[str] = None
    generation: int = 0
    local_status: str = 'clean'
    version_label: Optional[str] = None
    previous_version: Optional[str] = None
    changes: list[FileChange] = field(default_factory=list)
    conflict: Optional[str] = None
    safety: Optional[dict] = None


@dataclass
class SkillPlan:
    id: str
    kind: str
    scope: SkillScope
    items: list[PlanItem]
    expires_at: str

    def to_dict(self):
        return asdict(self)


@dataclass
class ItemResult:
    item_id: str
    status: str
    installation_id: Optional[str] = None
    runtime_skill_id: Optional[str] = None
    error: Optional[dict] = None


def management_error(exc: Exception) -> dict:
    if isinstance(exc, SkillManagementError):
        return exc.to_dict()
    # Do not expose request headers, credentials, arbitrary server bodies or
    # local filesystem paths through operation errors.
    return {
        'code': 'OPERATION_FAILED',
        'message': 'The operation could not be completed.',
        'retry_after': None
    }
