# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set

from ms_agent.utils.logger import get_logger

from .loader import SkillLoader
from .schema import SkillSchema, SkillSchemaParser
from .sources import SkillSource, SkillSourceType, parse_skill_source

logger = get_logger()

BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"
if not BUILTIN_SKILLS_DIR.exists():
    _repo_root = Path(__file__).parent.parent.parent
    _candidate = _repo_root / "skills"
    if _candidate.exists():
        BUILTIN_SKILLS_DIR = _candidate

USER_SKILLS_DIR = Path.home() / ".ms_agent" / "skills"


class SkillCatalog:
    """Unified skill catalog that loads, caches, and manages skills
    from multiple sources with priority-based override semantics.
    """

    def __init__(self, config=None):
        self._skills: Dict[str, SkillSchema] = {}
        self._sources: List[SkillSource] = []
        self._loader = SkillLoader()
        self._config = config
        self._disabled_skills: Set[str] = set()
        self._whitelist: Optional[Set[str]] = None
        self._cache_version: int = 0
        self._summary_cache: Optional[str] = None
        self._summary_cache_version: int = -1

    # ------------------------------------------------------------------ #
    #  Loading
    # ------------------------------------------------------------------ #

    def load_from_config(self, skills_config) -> None:
        """Load skills following the three-tier priority scan:
        built-in -> user home -> workspace / config-specified.
        """
        sources: List[SkillSource] = []

        # 1. Built-in skills (lowest priority)
        if BUILTIN_SKILLS_DIR.exists():
            sources.append(
                SkillSource(type=SkillSourceType.LOCAL_DIR,
                            path=str(BUILTIN_SKILLS_DIR)))

        # 2. User home skills
        for subdir in ("installed", "custom"):
            d = USER_SKILLS_DIR / subdir
            if d.exists():
                sources.append(
                    SkillSource(type=SkillSourceType.LOCAL_DIR,
                                path=str(d)))

        # 3a. Structured sources (higher priority)
        if hasattr(skills_config, "sources") and skills_config.sources:
            for src_cfg in skills_config.sources:
                sources.append(
                    SkillSource(
                        type=SkillSourceType(src_cfg.type),
                        path=getattr(src_cfg, "path", None),
                        repo_id=getattr(src_cfg, "repo_id", None),
                        url=getattr(src_cfg, "url", None),
                        revision=getattr(src_cfg, "revision", None),
                        subdir=getattr(src_cfg, "subdir", None),
                        enabled=getattr(src_cfg, "enabled", True),
                    ))
        # 3b. Simple path list (backward compat)
        elif hasattr(skills_config, "path") and skills_config.path:
            paths = skills_config.path
            if isinstance(paths, str):
                paths = [paths]
            for p in paths:
                sources.append(parse_skill_source(str(p)))

        # 4. Workspace auto-discover (highest priority)
        if getattr(skills_config, "auto_discover", False):
            workspace_skills = Path.cwd() / "skills"
            if workspace_skills.exists():
                sources.append(
                    SkillSource(type=SkillSourceType.LOCAL_DIR,
                                path=str(workspace_skills)))

        self._sources = sources
        self.load_from_sources(sources)

        # Apply whitelist / disabled filters
        if hasattr(skills_config, "whitelist"):
            wl = skills_config.whitelist
            if wl is None:
                self._whitelist = None
            elif isinstance(wl, (list, tuple)):
                self._whitelist = set(wl) if wl else set()
        if hasattr(skills_config, "disabled") and skills_config.disabled:
            self._disabled_skills = set(skills_config.disabled)

    def load_from_sources(self, sources: List[SkillSource]) -> None:
        self._sources = sources
        for source in sources:
            if not source.enabled:
                continue
            try:
                skills = self._materialize_and_load(source)
                for skill in skills.values():
                    self._register_skill(skill)
            except Exception as e:
                logger.warning(f"Failed to load skill source {source}: {e}")

    def _materialize_and_load(
            self, source: SkillSource) -> Dict[str, SkillSchema]:
        if source.type == SkillSourceType.LOCAL_DIR:
            return self._loader.load_skills(source.path)
        elif source.type == SkillSourceType.MODELSCOPE:
            return self._load_from_modelscope(source)
        elif source.type == SkillSourceType.GIT:
            return self._load_from_git(source)
        return {}

    def _load_from_modelscope(
            self, source: SkillSource) -> Dict[str, SkillSchema]:
        from modelscope import snapshot_download
        local_path = snapshot_download(
            repo_id=source.repo_id,
            revision=source.revision or "master")
        if source.subdir:
            local_path = str(Path(local_path) / source.subdir)
        return self._loader.load_skills(local_path)

    def _load_from_git(self, source: SkillSource) -> Dict[str, SkillSchema]:
        dest = Path(tempfile.mkdtemp(prefix="ms_agent_skill_"))
        cmd = ["git", "clone", "--depth", "1"]
        if source.revision:
            cmd += ["--branch", source.revision]
        cmd += [source.url, str(dest)]
        subprocess.run(cmd, check=True, capture_output=True)
        local_path = str(dest / source.subdir) if source.subdir else str(dest)
        return self._loader.load_skills(local_path)

    def _register_skill(self, skill: SkillSchema) -> None:
        """Register a skill; later registrations override earlier ones."""
        self._skills[skill.skill_id] = skill
        self._invalidate_cache()

    # ------------------------------------------------------------------ #
    #  Query
    # ------------------------------------------------------------------ #

    def get_enabled_skills(self) -> Dict[str, SkillSchema]:
        result = {}
        for sid, skill in self._skills.items():
            if sid in self._disabled_skills:
                continue
            if self._whitelist is not None and sid not in self._whitelist:
                continue
            result[sid] = skill
        return result

    def get_always_skills(self) -> Dict[str, SkillSchema]:
        result = {}
        for sid, skill in self.get_enabled_skills().items():
            frontmatter = SkillSchemaParser.parse_yaml_frontmatter(
                skill.content)
            if frontmatter and frontmatter.get("always", False):
                result[sid] = skill
        return result

    def get_skill(self, skill_id: str) -> Optional[SkillSchema]:
        return self._skills.get(skill_id)

    # ------------------------------------------------------------------ #
    #  Hot reload
    # ------------------------------------------------------------------ #

    def reload(self) -> None:
        self._skills.clear()
        self.load_from_sources(self._sources)

    def reload_skill(self, skill_id: str) -> Optional[SkillSchema]:
        skill = self._skills.get(skill_id)
        if skill and skill.skill_path.exists():
            reloaded = self._loader.reload_skill(str(skill.skill_path))
            if reloaded:
                self._skills[skill_id] = reloaded
                self._invalidate_cache()
                return reloaded
        return None

    def add_skill(self, skill_path: str) -> Optional[SkillSchema]:
        skills = self._loader.load_skills(skill_path)
        for skill in skills.values():
            self._register_skill(skill)
            return skill
        return None

    def remove_skill(self, skill_id: str) -> bool:
        if skill_id in self._skills:
            del self._skills[skill_id]
            self._invalidate_cache()
            return True
        return False

    def enable_skill(self, skill_id: str) -> None:
        self._disabled_skills.discard(skill_id)
        self._invalidate_cache()

    def disable_skill(self, skill_id: str) -> None:
        self._disabled_skills.add(skill_id)
        self._invalidate_cache()

    # ------------------------------------------------------------------ #
    #  Summary cache
    # ------------------------------------------------------------------ #

    def _invalidate_cache(self) -> None:
        self._cache_version += 1

    def get_skills_summary(self) -> str:
        if self._summary_cache_version == self._cache_version:
            return self._summary_cache or ""
        self._summary_cache = self._build_summary()
        self._summary_cache_version = self._cache_version
        return self._summary_cache

    def _build_summary(self) -> str:
        skills = self.get_enabled_skills()
        if not skills:
            return ""
        lines = []
        for sid, skill in sorted(skills.items()):
            lines.append(
                f"- **{skill.name}** (`{sid}`): {skill.description}")
        return "\n".join(lines)
