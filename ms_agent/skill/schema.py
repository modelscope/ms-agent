# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Skill Directory Schema

Defines the data structure and validation logic for Agent Skills.
Each Skill is represented as a self-contained directory with metadata.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from ms_agent.utils.logger import logger

from .skill_utils import SUPPORTED_READ_EXT, SUPPORTED_SCRIPT_EXT
from .spec import Spec


@dataclass
class SkillFile:
    """
    Represents a file within a Skill directory.

    Attributes:
        name: File name (e.g., "SKILL.md", "script.py")
        type: File extension/type (e.g., ".md", ".py", ".js")
        path: Relative path within Skill directory
        required: Whether this file is required
    """
    name: str
    type: str
    path: Path
    required: bool = False

    def __post_init__(self):
        """
        Validate file attributes after initialization.

        Raises:
            ValueError: If file attributes are invalid
        """
        if not self.name:
            raise ValueError('File name cannot be empty')
        if not self.type:
            raise ValueError('File type cannot be empty')

    def to_dict(self):
        """
        Convert SkillFile to dictionary representation.

        Returns:
            Dictionary containing file information
        """
        return {
            'name': self.name,
            'type': self.type,
            'path': str(self.path),
            'required': self.required
        }


@dataclass
class SkillSchema:
    """
    Complete schema for a Skill directory.

    Attributes:
        skill_id: Unique identifier for the Skill
        name: Skill name (max 64 characters)
        description: Skill description (max 1024 characters)
        content: Content of SKILL.md file
        files: List of files in the Skill directory
        skill_path: Absolute path to current skill directory
        version: Skill version (format: v0.1.2, default: latest)
        author: Skill author (optional)
        tags: List of tags for categorization (optional)
        scripts: List of script files (optional)
        references: List of reference documents (optional)
    """
    skill_id: str
    name: str
    description: str
    content: str
    files: List[SkillFile]
    version: str = 'latest'
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    scripts: List[SkillFile] = field(default_factory=list)
    references: List[SkillFile] = field(default_factory=list)
    resources: List[SkillFile] = field(default_factory=list)
    skill_path: Path = field(default_factory=lambda: Path.cwd().resolve())

    def __post_init__(self):
        """
        Validate schema after initialization.

        Raises:
            ValueError: If schema is invalid
        """
        if not self.skill_id:
            raise ValueError('Skill ID cannot be empty')
        if not self.name or len(self.name) > 64:
            raise ValueError('Skill name must be 1-64 characters')
        if not self.description or len(self.description) > 1024:
            raise ValueError('Skill description must be 1-1024 characters')
        if not self.files:
            raise ValueError('Skill must contain at least one file')

        # Ensure SKILL.md exists
        has_skill_md = any(f.name == 'SKILL.md' for f in self.files)
        if not has_skill_md:
            raise ValueError('Skill must contain SKILL.md file')

    def validate(self) -> bool:
        """
        Validate the complete Skill schema.

        Returns:
            True if valid, False otherwise
        """
        try:
            # Check directory exists
            if not self.skill_path.exists():
                return False

            # Check all required files exist
            for file in self.files:
                if file.required:
                    file_path = self.skill_path / file.path
                    if not file_path.exists():
                        return False

            # Validate metadata constraints
            if len(self.name) > 64 or len(self.description) > 1024:
                return False

            return True

        except Exception as e:
            logger.error(
                f'Skill validation failed with an unexpected error: {e}')
            return False

    def get_file_by_name(self, name: str) -> Optional[SkillFile]:
        """
        Get a file from the Skill by name.

        Args:
            name: File name to search for

        Returns:
            SkillFile if found, None otherwise
        """
        for file in self.files:
            if file.name == name:
                return file
        return None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert schema to dictionary representation.

        Returns:
            Dictionary containing all schema information
        """
        return {
            'skill_id':
            self.skill_id,
            'name':
            self.name,
            'description':
            self.description,
            'version':
            self.version,
            'author':
            self.author,
            'tags':
            self.tags,
            'skill_path':
            str(self.skill_path),
            'files': [{
                'name': f.name,
                'type': f.type,
                'path': f.path,
                'required': f.required
            } for f in self.files],
            'scripts':
            self.scripts,
            'references':
            self.references,
            'resources':
            self.resources,
        }


class SkillSchemaParser:
    """
    Parser for extracting and validating Skill schemas from directories.
    """

    @staticmethod
    def parse_yaml_frontmatter(content: str) -> Optional[Dict[str, Any]]:
        """
        Parse YAML frontmatter from markdown content.

        Args:
            content: Markdown file content

        Returns:
            Dictionary of frontmatter data, or None if not found
        """
        pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(pattern, content, re.DOTALL)

        if match:
            yaml_content = match.group(1)
            try:
                return yaml.safe_load(yaml_content)
            except yaml.YAMLError:
                return None
        return None

    @staticmethod
    def is_ignored_path(p: Path) -> bool:
        """
        Determine if a path should be ignored based on its name or suffix.

        Args:
            p: Path to check

        Returns:
            True if path should be ignored, False otherwise
        """
        ignored_names = {
            '.DS_Store', '__pycache__', '.git', '.gitignore', '.pytest_cache',
            '.mypy_cache'
        }
        ignored_suffixes = {'.pyc', '.pyo'}

        return (p.name in ignored_names) or (p.suffix in ignored_suffixes)

    @staticmethod
    def parse_skill_directory(directory_path: Path) -> Optional[SkillSchema]:
        """
        Parse a Skill directory and create a SkillSchema.

        Args:
            directory_path: Path to Skill directory

        Returns:
            SkillSchema if valid, None otherwise
        """
        if not directory_path.exists() or not directory_path.is_dir():
            return None

        # Read SKILL.md
        skill_md_path = directory_path / 'SKILL.md'
        if not skill_md_path.exists():
            return None

        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse metadata
        frontmatter = SkillSchemaParser.parse_yaml_frontmatter(content)
        if not frontmatter or 'name' not in frontmatter or 'description' not in frontmatter:
            return None

        # Generate skill_id from directory name
        skill_id = directory_path.name

        # Collect all files
        files = []
        scripts = []
        references = []
        resources = []

        for file_path in directory_path.rglob('*'):
            if file_path.is_file():
                if SkillSchemaParser.is_ignored_path(file_path):
                    continue

                file_type = file_path.suffix if file_path.suffix else '.unknown'

                skill_file = SkillFile(
                    name=file_path.name,
                    type=file_type,
                    path=file_path,
                    required=(file_path.name == 'SKILL.md'))
                files.append(skill_file)

                # Get scripts, references and resources
                if skill_file.type in SUPPORTED_SCRIPT_EXT:
                    scripts.append(skill_file)
                elif skill_file.type in ['.md'
                                         ] and skill_file.name != 'SKILL.md':
                    references.append(skill_file)
                else:
                    resources.append(skill_file)

        return SkillSchema(
            skill_id=skill_id,
            name=frontmatter['name'],
            description=frontmatter['description'],
            content=content,
            version=frontmatter.get('version', 'latest'),
            files=files,
            skill_path=directory_path.resolve(),
            author=frontmatter.get('author'),
            tags=frontmatter.get('tags', []),
            scripts=scripts,
            references=references,
            resources=resources,
        )

    @staticmethod
    def validate_skill_schema(schema: SkillSchema) -> List[str]:
        """
        Validate a Skill schema and return list of errors.

        Args:
            schema: SkillSchema to validate

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Check skill_id
        if not schema.skill_id:
            errors.append('Skill ID is required')

        # Check name length
        if len(schema.name) > 64:
            errors.append('Skill name exceeds 64 characters')

        # Check description length
        if len(schema.description) > 1024:
            errors.append('Skill description exceeds 1024 characters')

        # Check SKILL.md exists
        has_skill_md = any(f.name == 'SKILL.md' for f in schema.files)
        if not has_skill_md:
            errors.append('SKILL.md is required')

        # Check directory exists
        if not schema.skill_path.exists():
            errors.append(f'Directory does not exist: {schema.skill_path}')

        return errors


@dataclass
class SkillContext:
    """
    Context information for executing a Skill.
    """

    # The target skill
    skill: SkillSchema

    # The working directory (absolute path to skills folder's parent directory as default)
    root_path: Path = field(
        default_factory=lambda: Path.cwd().parent.resolve())

    # The target scripts to be executed
    scripts: List[Dict[str, Any]] = field(default_factory=list)

    # The reference documents
    references: List[Dict[str, Any]] = field(default_factory=list)

    # The resource documents
    resources: List[Dict[str, Any]] = field(default_factory=list)

    # The SPEC context
    spec: Optional[Spec] = None

    @staticmethod
    def _read_file_content(file_path: Union[str, Path]) -> str:
        """
        Read the content of a file.

        Args:
            file_path: Path to the file

        Returns:
            Content of the file as a string
        """
        # Read the file content by extensions
        file_path: Path = Path(file_path)

        if not file_path.exists() or not file_path.is_file():
            return ''

        ext: str = file_path.suffix.lower()
        if ext in SUPPORTED_READ_EXT:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.error(f'Failed to read file {file_path}: {e}')
                return ''

        return ''

    def __post_init__(self):

        # Initialize scripts info
        self.scripts = [
            {
                'name': script.name,
                'file': script.to_dict(),
                'path': str(script.path.resolve().relative_to(self.root_path)),
                'description':
                '',  # May need to call the LLM to generate description in the future
                'content': self._read_file_content(script.path.resolve()),
            } for script in self.skill.scripts
        ]

        # Initialize references info
        self.references = [
            {
                'name': reference.name,
                'file': reference.to_dict(),
                'path':
                str(reference.path.resolve().relative_to(self.root_path)),
                'description':
                '',  # May need to call the LLM to generate description in the future
                'content': self._read_file_content(reference.path.resolve()),
            } for reference in self.skill.references
        ]

        # Initialize resources info
        self.resources = [
            {
                'name': resource.name,
                'file': resource.to_dict(),
                'path':
                str(resource.path.resolve().relative_to(self.root_path)),
                'description':
                '',  # May need to call the LLM to generate description in the future
                'content': self._read_file_content(resource.path.resolve()),
            } for resource in self.skill.resources
            if resource.name not in ['SKILL.md', 'LICENSE.txt']
        ]

        # Initialize SPEC context
        if self.spec is None:
            self.spec = Spec(plan='', tasks='')


@dataclass
class ExecutionResult:
    """
    Result of executing a Skill.

    Attributes:
        success: Whether execution was successful
        output: Output content from execution
        messages: Messages or logs from execution
    """
    success: bool = True
    output: Any = None
    messages: Union[str, List[str]] = None

    def to_dict(self):
        """
        Convert ExecutionResult to dictionary representation.

        Returns:
            Dictionary containing execution result information
        """
        return {
            'success': self.success,
            'output': self.output,
            'messages': self.messages,
        }
