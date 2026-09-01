from __future__ import annotations

# Copyright (c) ModelScope Contributors. All rights reserved.
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from ms_agent.utils.logger import logger
from .discovery import SkillDescriptor
from .schema import SkillSchema, SkillSchemaParser


class SkillLoader:
    """
    Skill loader for loading and managing skills.

    Attributes:
        loaded_skills: Dictionary of loaded skill schemas
        parser: Skill schema parser instance
    """

    def __init__(self):
        self.loaded_skills: Dict[str, SkillSchema] = {}
        self.parser = SkillSchemaParser()
        self._discovery_cache: Dict[Path,
                                    tuple[tuple[int, int, int],
                                          Optional[SkillDescriptor]]] = {}

    def load_skills(
        self, skills: Union[str, List[str], List[SkillSchema]]
    ) -> Dict[str, SkillSchema]:
        """
        Load agent skills from various sources.

        Args:
            skills: Single skill directory,
                the root path of skill directories, list of skill directories, list of SkillSchema,
                or skill IDs on the ModelScope hub.

        Returns:
            Dictionary mapping skill_id@version to SkillSchema objects
        """
        all_skills = {}

        if not skills:
            logger.warning('No skills provided to load.')
            return all_skills

        if isinstance(skills, str):
            skill_list = [skills]
        elif all(isinstance(s, str) for s in skills) or all(
                isinstance(s, SkillSchema) for s in skills):
            skill_list = skills
        else:
            raise ValueError('Invalid skills input type.')

        for skill in skill_list:
            if isinstance(skill, SkillSchema):
                skill_key = self._get_skill_key(skill=skill)
                all_skills[skill_key] = skill
                logger.info(
                    f'Loaded skill from SkillSchema object: {skill_key}')
                continue

            skill_dir: Path = Path(skill)

            if not skill_dir.exists():
                logger.warning(f'Path does not exist: {skill_dir} - Skipping.')
                continue

            if self._is_skill_directory(skill_dir):
                skill_schema = self._load_single_skill(skill_dir=skill_dir)
                if skill_schema:
                    skill_key = f'{skill_schema.skill_id}@{skill_schema.version}'
                    all_skills[skill_key] = skill_schema
                    # logger.info(f'Successfully loaded skill: {skill_key}')
            else:
                skill_schema_dict: Dict[
                    str, SkillSchema] = self._scan_and_load_skills(skill_dir)
                all_skills.update(skill_schema_dict)

        self.loaded_skills.update(all_skills)

        return all_skills

    def discover_skills(
            self, skills: Union[str, List[str]]) -> Dict[str, SkillDescriptor]:
        """Discover local skills without traversing their support files.

        The source ordering, hidden-directory rule, maximum nesting depth,
        and "skill root is a leaf" rule match :meth:`load_skills`.  Only
        ``SKILL.md`` is read; callers that execute a skill must still use the
        full catalog loading path.
        """
        if not skills:
            return {}
        if isinstance(skills, str):
            skill_list = [skills]
        elif all(isinstance(skill, str) for skill in skills):
            skill_list = skills
        else:
            raise ValueError('Invalid skills input type.')

        discovered: Dict[str, SkillDescriptor] = {}
        active_roots: set[Path] = set()
        for value in skill_list:
            path = Path(value)
            if not path.exists():
                logger.warning(f'Path does not exist: {path} - Skipping.')
                continue
            roots: Iterable[Path]
            if self._is_skill_directory(path):
                roots = (path, )
            else:
                roots = self._iter_skill_directories(path)
            for root in roots:
                active_roots.add(root.resolve())
                descriptor = self._discover_single_skill(root)
                if descriptor is not None:
                    discovered[descriptor.key] = descriptor
        self._discovery_cache = {
            path: cached
            for path, cached in self._discovery_cache.items()
            if path in active_roots
        }
        return discovered

    def _is_skill_directory(self, path: Path) -> bool:
        """
        Check if a directory is a valid skill directory.

        Args:
            path: Path to check

        Returns:
            True if directory contains SKILL.md file
        """
        skill_md = path / 'SKILL.md'
        return skill_md.exists() and skill_md.is_file()

    def _load_single_skill(self, skill_dir: Path) -> Optional[SkillSchema]:
        """
        Load a single skill from directory.

        Args:
            skill_dir: Path to skill directory

        Returns:
            SkillSchema object if successful, None otherwise
        """
        try:
            skill_schema = self.parser.parse_skill_directory(skill_dir)

            if not skill_schema:
                logger.error(f'Failed to parse skill: {skill_dir}')
                return None

            validation_errors = self.parser.validate_skill_schema(skill_schema)
            if validation_errors:
                logger.warning(f'Skill validation warnings ({skill_dir}):')
                for error in validation_errors:
                    logger.warning(f'  - {error}')

            return skill_schema

        except Exception as e:
            logger.error(f'Error loading skill ({skill_dir}): {str(e)}')
            return None

    def _discover_single_skill(self,
                               skill_dir: Path) -> Optional[SkillDescriptor]:
        try:
            skill_dir = skill_dir.resolve()
            skill_md = skill_dir / 'SKILL.md'
            file_stat = skill_md.stat()
            fingerprint = (file_stat.st_mtime_ns, file_stat.st_ctime_ns,
                           file_stat.st_size)
            cached = self._discovery_cache.get(skill_dir)
            if cached is not None and cached[0] == fingerprint:
                return cached[1]

            content = skill_md.read_text(encoding='utf-8')
            frontmatter = self.parser.parse_yaml_frontmatter(content)
            if (not frontmatter or 'name' not in frontmatter
                    or 'description' not in frontmatter):
                self._discovery_cache[skill_dir] = (fingerprint, None)
                return None
            descriptor = SkillDescriptor(
                skill_id=skill_dir.name,
                name=frontmatter['name'],
                description=frontmatter['description'],
                content=content,
                version=frontmatter.get('version', 'latest'),
                author=frontmatter.get('author'),
                tags=tuple(frontmatter.get('tags') or []),
                skill_path=skill_dir,
            )
            self._discovery_cache[skill_dir] = (fingerprint, descriptor)
            return descriptor
        except Exception as exc:
            logger.error(f'Error discovering skill ({skill_dir}): {exc}')
            return None

    #: How deep _scan_and_load_skills descends below the scan root. Bounds
    #: symlink cycles; deep enough for organizational nesting (category dirs).
    _MAX_SCAN_DEPTH = 5

    def _iter_skill_directories(self, base_path: Path) -> Iterable[Path]:
        """Yield skill roots using the same bounded marker walk as loading."""
        if not base_path.is_dir():
            logger.warning(f'Not a valid directory: {base_path}')
            return

        def _walk(directory: Path, depth: int) -> Iterable[Path]:
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                return
            for item in entries:
                if not item.is_dir() or item.name.startswith('.'):
                    continue
                if self._is_skill_directory(item):
                    yield item
                elif depth < self._MAX_SCAN_DEPTH:
                    yield from _walk(item, depth + 1)

        yield from _walk(base_path, 1)

    def _scan_and_load_skills(self, base_path: Path) -> Dict[str, SkillSchema]:
        """
        Recursively scan a tree and load every skill root found.

        A skill root is a directory containing ``SKILL.md``; it is treated as
        a leaf — its subdirectories (``scripts/``, ``references/``, …) belong
        to the skill and are not descended into. Directories without a
        ``SKILL.md`` are organizational and are recursed. Hidden directories
        (``.hub``, ``.git``, …) are skipped.

        Args:
            base_path: Base directory to scan

        Returns:
            Dictionary mapping skill_id@version to SkillSchema objects
        """
        skills: Dict[str, SkillSchema] = {}

        for skill_dir in self._iter_skill_directories(base_path):
            skill = self._load_single_skill(skill_dir)
            if skill:
                skills[self._get_skill_key(skill=skill)] = skill
        return skills

    @staticmethod
    def _get_skill_key(skill: SkillSchema):
        """
        Generate a unique key for a skill based on its ID and version.

        Args:
            skill: SkillSchema object

        Returns:
            Unique skill key in the format 'skill_id@version'
        """
        return f'{skill.skill_id}@{skill.version}'

    def get_skill(self, skill_key: str) -> Optional[SkillSchema]:
        """
        Get a loaded skill by name.

        Args:
            skill_key: Skill name

        Returns:
            SkillSchema object if found, None otherwise
        """
        return self.loaded_skills.get(skill_key)

    def list_skills(self) -> List[str]:
        """
        List all loaded skill names.

        Returns:
            List of skill names
        """
        return list(self.loaded_skills.keys())

    def get_all_skills(self) -> Dict[str, SkillSchema]:
        """
        Get all loaded skills.

        Returns:
            Dictionary of all loaded skills
        """
        return self.loaded_skills.copy()

    def load_command_markdown(
        self,
        command_path: str | Path,
        *,
        plugin_id: str | None = None,
    ) -> Dict[str, SkillSchema]:
        """Load a plugin command ``*.md`` file as a virtual skill entry."""
        from .schema import SkillFile, SkillSchema

        path = Path(command_path)
        if not path.is_file():
            return {}
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            return {}
        frontmatter = self.parser.parse_yaml_frontmatter(content) or {}
        name = str(frontmatter.get('name') or path.stem)
        description = str(
            frontmatter.get('description') or f'Plugin command {name}')
        skill_id = (f'{plugin_id}:{name}' if plugin_id else f'command:{name}')
        body_text = re.sub(
            r'^---\s*\n.*?\n---\s*\n',
            '',
            content,
            count=1,
            flags=re.DOTALL,
        ).strip()
        skill = SkillSchema(
            skill_id=skill_id,
            name=name,
            description=description,
            content=body_text,
            files=[SkillFile(name='SKILL.md', type='.md', path=path)],
            skill_path=path.parent,
            version='latest',
            tags=['plugin-command'],
        )
        key = self._get_skill_key(skill=skill)
        return {key: skill}

    def reload_skill(self, skill_path: str) -> Optional[SkillSchema]:
        """
        Reload a skill from its directory.

        Args:
            skill_path: Path to skill directory

        Returns:
            Reloaded SkillSchema object if successful, None otherwise
        """
        path_obj = Path(skill_path)

        if not self._is_skill_directory(path_obj):
            logger.error(f'Not a valid skill directory: {skill_path}')
            return None

        skill = self._load_single_skill(path_obj)
        if skill:
            skill_key: str = self._get_skill_key(skill=skill)
            self.loaded_skills[skill_key] = skill
            logger.info(f'Successfully reloaded skill: {skill.name}')

        return skill


def load_skills(
    skills: Union[str, List[str],
                  List[SkillSchema]]) -> Dict[str, SkillSchema]:
    """
    Convenience function to load skills without creating a SkillLoader instance.

    Args:
        skills: Single skill directory,
            the root path of skill directories, list of skill directories, list of SkillSchema,
            or skill IDs on the ModelScope hub.

    Returns:
        Dictionary mapping skill_id@version to SkillSchema objects
    """
    loader = SkillLoader()
    return loader.load_skills(skills)
