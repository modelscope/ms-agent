import os
import shutil
from dataclasses import asdict, replace
from pathlib import Path

from ms_agent.project.store import JSONFileStore
from ms_agent.project.types import DEFAULT_PROJECT_ID, Project, _new_id, _now_iso


class ProjectManager:
    """Project CRUD. Pure SDK interface, no IO assumptions."""

    PROJECTS_DIR = 'projects'
    META_DIR = '.ms-agent'
    META_FILE = 'project.json'

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
    ) -> Project:
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
        self._init_project_dirs(project)
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
            meta_file = entry / self.META_DIR / self.META_FILE
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
        default_path = self._projects_root / DEFAULT_PROJECT_ID
        meta_file = default_path / self.META_DIR / self.META_FILE
        if meta_file.exists():
            return
        project = Project(
            id=DEFAULT_PROJECT_ID,
            name='Default',
            path=str(default_path.resolve()),
        )
        self._init_project_dirs(project)
        self._save_meta(project)

    def _init_project_dirs(self, project: Project) -> None:
        project_dir = self._projects_root / project.id
        (project_dir / self.META_DIR).mkdir(parents=True, exist_ok=True)
        (project_dir / self.META_DIR / 'sessions').mkdir(exist_ok=True)
        project_path = Path(project.path)
        project_path.mkdir(parents=True, exist_ok=True)
        (project_path / 'workspace').mkdir(exist_ok=True)

    def _meta_store(self, project_id: str) -> JSONFileStore:
        return JSONFileStore(
            self._projects_root / project_id / self.META_DIR / self.META_FILE
        )

    def _save_meta(self, project: Project) -> None:
        project_dir = self._projects_root / project.id
        meta_dir = project_dir / self.META_DIR
        meta_dir.mkdir(parents=True, exist_ok=True)
        store = JSONFileStore(meta_dir / self.META_FILE)
        store.write(asdict(project))
