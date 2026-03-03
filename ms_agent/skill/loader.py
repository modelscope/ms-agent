# Copyright (c) ModelScope Contributors. All rights reserved.
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

from ms_agent.utils.logger import logger

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

        def is_skill_id(s: str) -> bool:
            return '/' in s and len(s.split('/')) == 2 and all(
                s.split('/')) and not os.path.exists(s)

        if isinstance(skills, str):
            # Could be a single skill path, root path of skills, or skill ID on ModelScope hub
            skill_list = [skills]
        elif all(isinstance(s, str) for s in skills) or all(
                isinstance(s, SkillSchema) for s in skills):
            skill_list = skills
        else:
            raise ValueError('Invalid skills input type.')

        for skill in skill_list:

            if is_skill_id(skill):
                from modelscope import snapshot_download
                skill_path: str = snapshot_download(repo_id=skill)
                skill = skill_path

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

    def _scan_and_load_skills(self, base_path: Path) -> Dict[str, SkillSchema]:
        """
        Scan directory and load all skills found.

        Args:
            base_path: Base directory to scan

        Returns:
            Dictionary mapping skill_id@version to SkillSchema objects
        """
        skills = {}

        if not base_path.is_dir():
            logger.warning(f'Not a valid directory: {base_path}')
            return skills

        for item in base_path.iterdir():
            if item.is_dir() and self._is_skill_directory(item):
                skill = self._load_single_skill(item)
                if skill:
                    skill_key = self._get_skill_key(skill=skill)
                    skills[skill_key] = skill
                    # logger.info(
                    #     f'Successfully loaded skill: {skill_key} (from {item})'
                    # )

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
