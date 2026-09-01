"""SkillsConfigManager — CRUD for global/project skills.json.

Provides the persistent write-side for skill configuration. The read-side
(merge_skills_configs) already exists in resolver.py and is reused here.

Storage format (skills.json):
    {
        "sources": ["/path/to/skills", "./relative/to/scope-root",
                    "modelscope://org/skill-pack"],
        "disabled": ["skill-a", "skill-b"]
    }

Read-side semantics (loads and list_sources):
  * Relative source entries are anchored at the scope root — the global dir
    for the global file, the project root (parent of ``.ms_agent/``) for a
    project file — never the process cwd. The file itself keeps the raw
    strings (writers round-trip them untouched) so hand-written relative
    paths stay portable.
  * Each scope can have two implicit discovery trees: the cross-agent standard
    ``.agents/skills`` directory followed by ms-agent's managed live tree
    (``<global_dir>/skills`` or ``<project>/.ms_agent/skills``). Dropping a
    Skill directory into either registers it without touching skills.json
    ("existence = filesystem, state = disabled list"). The managed tree wins
    over the standard tree, and explicit sources remain highest priority.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ms_agent.config.resolver import merge_skills_configs

SKILLS_FILE = 'skills.json'
#: Live-tree directory name, shared by both scopes (``<global_dir>/skills``
#: and ``<project>/.ms_agent/skills``).
SKILLS_TREE_DIR = 'skills'


def global_standard_skills_tree() -> Path:
    """Cross-agent personal skills: ``~/.agents/skills``.

    This directory is read-only from ms-agent's point of view.  It is an
    implicit discovery root, never written to ``skills.json`` and never used as
    an install destination.
    """
    return Path.home() / '.agents' / SKILLS_TREE_DIR


def project_standard_skills_tree(project_path: str) -> Path:
    """Cross-agent project skills: ``<project>/.agents/skills``."""
    root = Path(os.path.expanduser(str(project_path))).resolve()
    return root / '.agents' / SKILLS_TREE_DIR

#: Remote-source prefixes that must never be path-anchored.
_REMOTE_PREFIXES = ('modelscope://', 'http://', 'https://', 'git://', '@')
#: ``owner/repo`` hub shorthand (mirrors sources.parse_skill_source).
_OWNER_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def resolve_source_entry(entry: Any, base: Path) -> Any:
    """Anchor a relative local-path source entry at *base*.

    Remote schemes, hub shorthands and absolute paths pass through
    untouched; ``~`` expands to the user home. ``owner/repo`` stays a hub
    id unless it actually exists under *base*.
    """
    if not isinstance(entry, str):
        return entry
    raw = entry.strip()
    if not raw or raw.startswith(_REMOTE_PREFIXES):
        return entry
    if raw.startswith('~'):
        return str(Path(raw).expanduser())
    if os.path.isabs(raw):
        return entry
    candidate = Path(base) / raw
    if (not raw.startswith(('./', '../')) and _OWNER_REPO_RE.match(raw)
            and not candidate.exists()):
        return entry  # hub shorthand, not a local dir
    return str(candidate.resolve())


class SkillsConfigManager:
    """Global and project-level skills configuration CRUD."""

    def __init__(self, global_dir: str = '~/.ms_agent') -> None:
        self._global_dir = Path(os.path.expanduser(global_dir))

    # -- load (read-side: anchored paths + implicit live tree) --

    def load_global(self) -> Dict[str, Any]:
        data = self._read(self._global_path())
        return self._resolved(
            data,
            base=self._global_dir,
            trees=(global_standard_skills_tree(), self.global_skills_tree()),
        )

    def load_project(self, project_path: str) -> Dict[str, Any]:
        data = self._read(self._project_path(project_path))
        base = Path(os.path.expanduser(str(project_path))).resolve()
        return self._resolved(
            data,
            base=base,
            trees=(
                project_standard_skills_tree(project_path),
                self.project_skills_tree(project_path),
            ),
        )

    def load_merged(self,
                    project_path: Optional[str] = None) -> Dict[str, Any]:
        g = self.load_global()
        p = self.load_project(project_path) if project_path else {}
        return merge_skills_configs(g, p)

    def global_skills_tree(self) -> Path:
        """The global live tree: ``<global_dir>/skills``."""
        return self._global_dir / SKILLS_TREE_DIR

    @staticmethod
    def project_skills_tree(project_path: str) -> Path:
        """The project live tree: ``<project>/.ms_agent/skills`` (legacy
        ``.ms-agent/skills`` honored when only it exists)."""
        from ms_agent.project.paths import (INTERNAL_DIR_NAME,
                                            LEGACY_INTERNAL_DIR_NAME)
        root = Path(os.path.expanduser(str(project_path))).resolve()
        new = root / INTERNAL_DIR_NAME / SKILLS_TREE_DIR
        if new.exists():
            return new
        legacy = root / LEGACY_INTERNAL_DIR_NAME / SKILLS_TREE_DIR
        return legacy if legacy.exists() else new

    @staticmethod
    def _resolved(data: Dict[str, Any], base: Path,
                  trees: tuple[Path, ...]) -> Dict[str, Any]:
        """Anchor relative sources at *base* and prepend implicit trees.

        Trees are ordered from lower to higher priority.  The standard
        ``.agents/skills`` root therefore comes before ms-agent's managed live
        tree, while explicit sources still come last and retain their existing
        precedence.
        """
        out = dict(data)
        sources = [
            resolve_source_entry(s, base) for s in (data.get('sources') or [])
        ]
        implicit: List[str] = []
        for tree in trees:
            if not tree.is_dir():
                continue
            tree_str = str(tree.resolve())
            if tree_str not in implicit and tree_str not in sources:
                implicit.append(tree_str)
        if implicit or sources or 'sources' in data:
            out['sources'] = implicit + sources
        return out

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
        if scope == 'project':
            base = Path(os.path.expanduser(str(project_path))).resolve()
        else:
            base = self._global_dir
        data = self._read(path)
        sources: List[str] = data.get('sources', [])
        # Match the raw string or its anchored form, so callers may pass
        # either what the file stores or what list_sources returned.
        data['sources'] = [
            s for s in sources
            if s != source and resolve_source_entry(s, base) != source
        ]
        self._write(path, data)

    def list_sources(
        self,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> List[str]:
        if scope == 'project':
            if not project_path:
                raise ValueError('project_path required for project scope')
            return list(self.load_project(project_path).get('sources', []))
        return list(self.load_global().get('sources', []))

    def list_explicit_sources(
        self,
        scope: str = 'global',
        project_path: Optional[str] = None,
    ) -> List[str]:
        """Configured sources only, excluding all implicit discovery trees.

        Callers that remove a legacy path reference must not accidentally treat
        ``~/.agents/skills`` or an ms-agent live tree as a removable
        ``skills.json`` entry.
        """
        if scope == 'project':
            if not project_path:
                raise ValueError('project_path required for project scope')
            base = Path(os.path.expanduser(str(project_path))).resolve()
            data = self._read(self._project_path(project_path))
        else:
            base = self._global_dir
            data = self._read(self._global_path())
        return [
            resolve_source_entry(source, base)
            for source in (data.get('sources') or [])
        ]

    # -- internal --

    def _global_path(self) -> Path:
        return self._global_dir / SKILLS_FILE

    def _project_path(self, project_path: str) -> Path:
        from ms_agent.project.paths import project_internal_file
        return project_internal_file(project_path, SKILLS_FILE)

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
        # replace() is atomic and cross-platform; rename() raises on Windows
        # when the destination already exists.
        tmp.replace(path)
