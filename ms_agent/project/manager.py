import os
import shutil
from dataclasses import asdict, replace
from pathlib import Path

from ms_agent.project.store import JSONFileStore
from ms_agent.project.types import DEFAULT_PROJECT_ID, Project, _new_id, _now_iso


class ProjectManager:
    """Project CRUD. Pure SDK interface, no IO assumptions."""

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

    def __init__(self, base_dir: str = '~/.ms_agent') -> None:
        self._base = Path(os.path.expanduser(base_dir))
        self._projects_root = self._base / self.PROJECTS_DIR
        self._projects_root.mkdir(parents=True, exist_ok=True)
        self._ensure_default_project()

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

    def open_folder(
        self,
        path: str,
        name: str | None = None,
        instruction: str = '',
        memory_enabled: bool = False,
        memory_backend: str | None = None,
    ) -> Project:
        """Open an existing directory as a project (Codex "use an existing folder").

        Unlike :meth:`create`, the project's identity **is the folder**:
        ``id = project_key(path)``. Consequences:

        - **Dedup by path** — reopening the same folder returns the same project
          (no duplicate), so history is continuous across reopens.
        - **No ``workspace/`` pollution** — the agent works in the folder
          directly; only the metadata under ``<base>/projects/<key>/`` is written
          here. The folder's own ``.ms_agent/`` internals are created lazily by
          the runtime, not by this call.
        """
        from ms_agent.project.paths import project_key

        work_dir = str(Path(os.path.expanduser(path)).resolve())
        project_id = project_key(work_dir)
        existing = self.get(project_id)
        if existing is not None:
            return existing
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
        return Project(**data)

    def list(self) -> list[Project]:
        projects: list[Project] = []
        if not self._projects_root.exists():
            return projects
        for entry in sorted(self._projects_root.iterdir()):
            if not entry.is_dir():
                continue
            meta_file = self._meta_file(entry.name)
            if meta_file.exists():
                store = JSONFileStore(meta_file)
                try:
                    projects.append(Project(**store.read()))
                except (TypeError, KeyError):
                    pass
        return projects

    def update(self, project_id: str, **kwargs: object) -> Project:
        old = self.get(project_id)
        if old is None:
            raise ValueError(f'Project {project_id} not found')
        kwargs['updated_at'] = _now_iso()
        new = replace(old, **kwargs)
        self._save_meta(new)
        return new

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
        if project is None:
            self._ensure_default_project()
            project = self.get(DEFAULT_PROJECT_ID)
        assert project is not None
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
        self._init_project_dirs(project)
        self._save_meta(project)

    def _init_project_dirs(
        self, project: Project, init_workspace: bool = True
    ) -> None:
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
        store.write(asdict(project))
