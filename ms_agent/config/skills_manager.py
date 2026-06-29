"""SkillsConfigManager — CRUD for global/project skills.json.

Provides the persistent write-side for skill configuration. The read-side
(merge_skills_configs) already exists in resolver.py and is reused here.

Storage format (skills.json):
    {
        "sources": ["/path/to/skills", "modelscope://org/skill-pack"],
        "disabled": ["skill-a", "skill-b"]
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.config.resolver import merge_skills_configs

SKILLS_FILE = 'skills.json'
PROJECT_META_DIR = '.ms-agent'


class SkillsConfigManager:
    """Global and project-level skills configuration CRUD."""

    def __init__(self, global_dir: str = '~/.ms_agent') -> None:
        self._global_dir = Path(os.path.expanduser(global_dir))

    # -- load --

    def load_global(self) -> Dict[str, Any]:
        return self._read(self._global_path())

    def load_project(self, project_path: str) -> Dict[str, Any]:
        return self._read(self._project_path(project_path))

    def load_merged(self, project_path: Optional[str] = None) -> Dict[str, Any]:
        g = self.load_global()
        p = self.load_project(project_path) if project_path else {}
        return merge_skills_configs(g, p)

    # -- enable/disable --

    def set_skill_enabled(
        self,
        skill_id: str,
        enabled: bool,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> None:
        path = self._resolve_path(scope, project_path)
        data = self._read(path)
        disabled: List[str] = data.get('disabled', [])

        if enabled:
            disabled = [s for s in disabled if s != skill_id]
        else:
            if skill_id not in disabled:
                disabled.append(skill_id)

        data['disabled'] = sorted(disabled)
        self._write(path, data)

    # -- sources --

    def add_source(
        self,
        source: str,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> None:
        path = self._resolve_path(scope, project_path)
        data = self._read(path)
        sources: List[str] = data.get('sources', [])
        if source not in sources:
            sources.append(source)
        data['sources'] = sources
        self._write(path, data)

    def remove_source(
        self,
        source: str,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> None:
        path = self._resolve_path(scope, project_path)
        data = self._read(path)
        sources: List[str] = data.get('sources', [])
        data['sources'] = [s for s in sources if s != source]
        self._write(path, data)

    def list_sources(
        self,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> List[str]:
        path = self._resolve_path(scope, project_path)
        data = self._read(path)
        return data.get('sources', [])

    # -- internal --

    def _global_path(self) -> Path:
        return self._global_dir / SKILLS_FILE

    def _project_path(self, project_path: str) -> Path:
        return Path(project_path) / PROJECT_META_DIR / SKILLS_FILE

    def _resolve_path(self, scope: str, project_path: Optional[str]) -> Path:
        if scope == 'project':
            if not project_path:
                raise ValueError('project_path required for project scope')
            return self._project_path(project_path)
        return self._global_path()

    @staticmethod
    def _read(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _write(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.rename(path)
