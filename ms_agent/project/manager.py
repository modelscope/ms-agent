from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict, replace
from pathlib import Path

from ms_agent.utils.file_lock import locked
from ms_agent.project.store import JSONFileStore
from ms_agent.project.types import (DEFAULT_PROJECT_ID, Project, _new_id,
                                    _now_iso)


class DefaultProjectMissingError(ValueError):
    """Previously initialized storage has lost its default project record."""


class ProjectManager:
    """File-backed project CRUD with optional explicit initialization."""

    PROJECTS_DIR = 'projects'
    META_DIR = '.ms_agent'
    LEGACY_META_DIR = '.ms-agent'
    META_FILE = 'project.json'

    def _meta_file(self, project_id: str) -> Path:
        """Project meta path — new ``.ms_agent`` first, legacy ``.ms-agent`` if
        only that exists (read-compat)."""
        base = self._projects_root / project_id
        new = base / self.META_DIR / self.META_FILE
        if new.exists():
            return new
        legacy = base / self.LEGACY_META_DIR / self.META_FILE
        if legacy.exists():
            return legacy
        return new

    def __init__(self, base_dir: str = '~/.ms_agent', *,
                 auto_initialize: bool = True) -> None:
        self._base = Path(base_dir).expanduser().resolve()
        self._projects_root = self._base / self.PROJECTS_DIR
        self._auto_initialize = auto_initialize
        if auto_initialize:
            self.initialize()

    @property
    def base_dir(self) -> Path:
        return self._base

    @locked(lambda self: self._projects_root)
    def initialize(self) -> None:
        """Prepare first-use storage; never recreate lost project metadata."""
        marker = JSONFileStore(self._base / '.projects.initialized')
        project = self.get(DEFAULT_PROJECT_ID)
        if project is None:
            if self._meta_file(DEFAULT_PROJECT_ID).exists():
                raise ValueError('Default project metadata is empty; restore project.json from a backup')
            default_dir = self._projects_root / DEFAULT_PROJECT_ID
            has_files = default_dir.exists() and any(p.is_file() for p in default_dir.rglob('*'))
            if marker.exists() or has_files:
                raise DefaultProjectMissingError(
                    f'Default project metadata is missing: {self._meta_file(DEFAULT_PROJECT_ID)}')
            self._ensure_default_project()
        if not marker.exists():
            marker.write({'version': 1})

    def default_project_needs_repair(self) -> bool:
        """Inspect missing metadata without initializing or modifying storage."""
        metadata = self._meta_file(DEFAULT_PROJECT_ID)
        if metadata.exists() or metadata.is_symlink():
            try:
                project = self.get(DEFAULT_PROJECT_ID)
            except (TypeError, ValueError) as exc:
                raise ValueError('Existing project.json is invalid; restore it from a backup') from exc
            if project is None:
                raise ValueError('Existing project.json is empty or unreadable; restore it from a backup')
            return False
        default_dir = self._projects_root / DEFAULT_PROJECT_ID
        has_files = default_dir.is_dir() and any(p.is_file() for p in default_dir.rglob('*'))
        if not (self._base / '.projects.initialized').exists() and not has_files:
            raise ValueError('No previous default project data found; start MS-Agent normally to initialize it')
        return True

    @locked(lambda self: self._projects_root)
    def repair_default_project(self) -> Path | None:
        """Back up managed project data before explicitly recreating missing metadata."""
        if not self.default_project_needs_repair():
            return None
        backups = self._base / 'backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix='default-project-', dir=backups))
        project_dir = self._projects_root / DEFAULT_PROJECT_ID
        marker = self._base / '.projects.initialized'
        try:
            if project_dir.exists():
                shutil.copytree(project_dir, backup / 'projects' / DEFAULT_PROJECT_ID, symlinks=True)
            if marker.exists():
                shutil.copy2(marker, backup / marker.name)
        except OSError as exc:
            raise OSError(f'Backup failed; project data was not changed. Partial backup: {backup}') from exc
        try:
            self._ensure_default_project()
            self.initialize()
        except (OSError, ValueError) as exc:
            raise RuntimeError(f'Repair did not finish. Backup: {backup}. Resolve the error and retry.') from exc
        return backup

    def session_manager(self, project: Project, *, auto_initialize: bool = True):
        from ms_agent.project.session import SessionManager
        return SessionManager(project, base_dir=self._base,
                              auto_initialize=auto_initialize, require_project=True)

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def create(
        self,
        name: str,
        path: str | None = None,
        instruction: str = '',
        memory_enabled: bool = False,
        memory_backend: str | None = None,
        init_workspace: bool = True,
    ) -> Project:
        """Create a new project (Codex "start from scratch").

        Identity is a random id; ``path`` defaults to the managed location
        ``<base>/projects/<id>/``. Set ``init_workspace=False`` to skip the
        ``<path>/workspace/`` subdir (the runtime writes products directly under
        ``output_dir``, so that subdir is optional).
        """
        project_id = _new_id()
        if path is None:
            path = str(self._projects_root / project_id)
        path = str(Path(os.path.expanduser(path)).resolve())

        project = Project(
            id=project_id,
            name=name,
            path=path,
            instruction=instruction,
            memory_enabled=memory_enabled,
            memory_backend=memory_backend,
        )
        self._init_project_dirs(project, init_workspace=init_workspace)
        self._save_meta(project)
        return project

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def open_folder(
        self,
        path: str,
        name: str | None = None,
        instruction: str = '',
        memory_enabled: bool = False,
        memory_backend: str | None = None,
    ) -> Project:
        """Open an existing directory as a project (Codex "use an existing folder").

        Unlike :meth:`create`, a brand-new mount uses ``id = project_key(path)``.
        If this folder is already a registered project — including one created
        with a random id — that record is returned so TUI and WebUI share one
        session tree.

        - **Dedup by path** — reopening the same folder returns the same project
          (no duplicate), so history is continuous across reopens.
        - **No ``workspace/`` pollution** — the agent works in the folder
          directly; only the metadata under ``<base>/projects/<key>/`` is written
          here. The folder's own ``.ms_agent/`` internals are created lazily by
          the runtime, not by this call.
        """
        from ms_agent.project.paths import project_key

        work_dir = str(Path(os.path.expanduser(path)).resolve())
        existing = self.find_by_path(work_dir)
        if existing is not None:
            return existing
        project_id = project_key(work_dir)
        project = Project(
            id=project_id,
            name=name or Path(work_dir).name or project_id,
            path=work_dir,
            instruction=instruction,
            memory_enabled=memory_enabled,
            memory_backend=memory_backend,
        )
        self._init_project_dirs(project, init_workspace=False)
        self._save_meta(project)
        return project

    def get(self, project_id: str) -> Project | None:
        store = self._meta_store(project_id)
        if not store.exists():
            return None
        data = store.read()
        return Project(**{k: v for k, v in data.items() if k in Project.__dataclass_fields__}) if data else None

    def find_by_path(self, path: str) -> Project | None:
        """Return the registered project whose ``path`` is this directory.

        Used so a WebUI ``create()`` project (random id, path = that folder)
        and a later TUI/WebUI ``open_folder`` of the same directory stay one
        project. Comparison is on resolved absolute paths.
        """
        try:
            work_dir = str(Path(os.path.expanduser(path)).resolve())
        except OSError:
            return None
        for project in self.list():
            try:
                if str(Path(project.path).expanduser().resolve()) == work_dir:
                    return project
            except OSError:
                continue
        return None

    def list(self) -> list[Project]:
        projects: list[Project] = []
        try:
            entries = sorted(self._projects_root.iterdir())
        except FileNotFoundError:
            return projects
        for entry in entries:
            if not entry.is_dir():
                continue
            meta_file = self._meta_file(entry.name)
            if meta_file.exists():
                store = JSONFileStore(meta_file)
                try:
                    data = store.read()
                    if data:
                        projects.append(Project(**{k: v for k, v in data.items()
                                                   if k in Project.__dataclass_fields__}))
                except (TypeError, KeyError):
                    pass
        return projects

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def update(self, project_id: str, **kwargs: object) -> Project:
        old = self.get(project_id)
        if old is None:
            raise ValueError(f'Project {project_id} not found')
        kwargs['updated_at'] = _now_iso()
        new = replace(old, **kwargs)
        self._save_meta(new)
        return new

    @locked(lambda self, *args, **kwargs: self._projects_root)
    def delete(self, project_id: str) -> None:
        if project_id == DEFAULT_PROJECT_ID:
            raise ValueError('Cannot delete the default project')
        project = self.get(project_id)
        if project is None:
            return
        project_dir = self._projects_root / project_id
        if project_dir.exists():
            shutil.rmtree(project_dir)

    def get_default_project(self) -> Project:
        project = self.get(DEFAULT_PROJECT_ID)
        if project is None and self._auto_initialize:
            self.initialize()
            project = self.get(DEFAULT_PROJECT_ID)
        if project is None:
            raise ValueError('Default project is not initialized or its metadata is missing')
        return project

    # -- internal --

    def _ensure_default_project(self) -> None:
        meta_file = self._meta_file(DEFAULT_PROJECT_ID)
        if meta_file.exists():
            return
        default_path = self._projects_root / DEFAULT_PROJECT_ID
        project = Project(
            id=DEFAULT_PROJECT_ID,
            name='Default',
            path=str(default_path.resolve()),
        )
        # The runtime writes products directly under output_dir (== project
        # path), so the ``workspace/`` subdir is unused clutter — skip it for
        # the default project just like open_folder does for mounted ones.
        self._init_project_dirs(project, init_workspace=False)
        self._save_meta(project)

    def _init_project_dirs(self,
                           project: Project,
                           init_workspace: bool = True) -> None:
        project_dir = self._projects_root / project.id
        (project_dir / self.META_DIR).mkdir(parents=True, exist_ok=True)
        # Sessions live at <id>/sessions (flat), matching SessionManager
        # (paths.py) — no meta-nested sessions dir.
        (project_dir / 'sessions').mkdir(exist_ok=True)
        project_path = Path(project.path)
        project_path.mkdir(parents=True, exist_ok=True)
        # The workspace/ subdir is optional (the runtime writes under output_dir
        # directly). Skip it for open_folder so an existing folder stays clean.
        if init_workspace:
            (project_path / 'workspace').mkdir(exist_ok=True)

    def _meta_store(self, project_id: str) -> JSONFileStore:
        return JSONFileStore(self._meta_file(project_id))

    def _save_meta(self, project: Project) -> None:
        project_dir = self._projects_root / project.id
        meta_dir = project_dir / self.META_DIR
        meta_dir.mkdir(parents=True, exist_ok=True)
        store = JSONFileStore(meta_dir / self.META_FILE)
        data = self._meta_store(project.id).read()
        data.update(asdict(project))
        store.write(data)
