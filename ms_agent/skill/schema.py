# Copyright (c) ModelScope Contributors. All rights reserved.
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

from .spec import Spec

SUPPORTED_SCRIPT_EXT = ('.py', '.sh', '.js')
SUPPORTED_READ_EXT = ('.md', '.txt', '.py', '.json', '.yaml', '.yml', '.sh',
                      '.js', '.html', '.xml')


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
class SkillExecutionPlan:
    """
    Execution plan generated from progressive skill analysis.

    Attributes:
        can_handle: Whether the skill can handle the user query.
        plan_summary: Brief summary of the execution plan.
        steps: List of execution steps.
        required_scripts: Script names needed for execution.
        required_references: Reference names needed.
        required_resources: Resource names needed.
        required_packages: Python packages needed for execution.
        parameters: Parameters extracted from user query.
        reasoning: Explanation of the plan.
    """
    can_handle: bool = False
    plan_summary: str = ''
    steps: List[Dict[str, Any]] = field(default_factory=list)
    required_scripts: List[str] = field(default_factory=list)
    required_references: List[str] = field(default_factory=list)
    required_resources: List[str] = field(default_factory=list)
    required_packages: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ''


@dataclass
class SkillContext:
    """
    Context information for executing a Skill.

    Supports progressive/lazy loading - resources are only loaded when needed.
    """

    # The target skill
    skill: SkillSchema

    # User query that triggered this skill
    query: str = ''

    # The working directory (absolute path to skills folder's parent directory)
    root_path: Path = field(
        default_factory=lambda: Path.cwd().parent.resolve())

    # Execution plan from progressive analysis
    plan: Optional[SkillExecutionPlan] = None

    # Loaded scripts (lazy loaded based on plan)
    scripts: List[Dict[str, Any]] = field(default_factory=list)

    # Loaded references (lazy loaded based on plan)
    references: List[Dict[str, Any]] = field(default_factory=list)

    # Loaded resources (lazy loaded based on plan)
    resources: List[Dict[str, Any]] = field(default_factory=list)

    # The SPEC context for execution tracking
    spec: Optional[Spec] = None

    # Whether resources have been loaded
    _resources_loaded: bool = field(default=False, repr=False)

    @staticmethod
    def _read_file_content(file_path: Union[str, Path]) -> str:
        """
        Read the content of a file.

        Args:
            file_path: Path to the file

        Returns:
            Content of the file as a string
        """
        file_path = Path(file_path)

        if not file_path.exists() or not file_path.is_file():
            return ''

        ext = file_path.suffix.lower()
        if ext in SUPPORTED_READ_EXT:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                logger.error(f'Failed to read file {file_path}: {e}')
                return ''

        return ''

    def __post_init__(self):
        """Initialize SPEC context only, defer resource loading."""
        if self.spec is None:
            self.spec = Spec(plan='', tasks='')

    @property
    def skill_dir(self) -> Path:
        """Get the skill's directory path."""
        return self.skill.skill_path

    def get_scripts_list(self) -> List[str]:
        """Get list of available script names without loading content."""
        return [s.name for s in self.skill.scripts]

    def get_references_list(self) -> List[str]:
        """Get list of available reference names without loading content."""
        return [r.name for r in self.skill.references]

    def get_resources_list(self) -> List[str]:
        """Get list of available resource names without loading content."""
        return [
            r.name for r in self.skill.resources
            if r.name not in ['SKILL.md', 'LICENSE.txt']
        ]

    def _get_resource_path(self, file_path: Path) -> str:
        """
        Get path string for a resource file.

        Tries relative path first, falls back to absolute path.

        Args:
            file_path: Path to the resource file.

        Returns:
            Path string (relative if possible, absolute otherwise).
        """
        resolved_path = file_path.resolve()
        try:
            return str(resolved_path.relative_to(self.root_path.resolve()))
        except ValueError:
            # Path is not under root_path, use absolute path
            return str(resolved_path)

    def load_scripts(self, names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Load specific scripts by name, or all if names is None.

        Args:
            names: List of script names to load, or None for all.

        Returns:
            List of loaded script dictionaries with content.
        """
        target_scripts = self.skill.scripts
        if names:
            target_scripts = [s for s in self.skill.scripts if s.name in names]

        loaded = []
        for script in target_scripts:
            abs_path = script.path.resolve()
            loaded.append({
                'name': script.name,
                'file': script.to_dict(),
                'path': self._get_resource_path(script.path),
                'abs_path': str(abs_path),
                'content': self._read_file_content(abs_path),
            })
        self.scripts.extend(loaded)
        return loaded

    def load_references(self, names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Load specific references by name, or all if names is None.

        Args:
            names: List of reference names to load, or None for all.

        Returns:
            List of loaded reference dictionaries with content.
        """
        target_refs = self.skill.references
        if names:
            target_refs = [r for r in self.skill.references if r.name in names]

        loaded = []
        for ref in target_refs:
            abs_path = ref.path.resolve()
            loaded.append({
                'name': ref.name,
                'file': ref.to_dict(),
                'path': self._get_resource_path(ref.path),
                'abs_path': str(abs_path),
                'content': self._read_file_content(abs_path),
            })
        self.references.extend(loaded)
        return loaded

    def load_resources(self, names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Load specific resources by name, or all if names is None.

        Args:
            names: List of resource names to load, or None for all.

        Returns:
            List of loaded resource dictionaries with content.
        """
        target_res = [
            r for r in self.skill.resources
            if r.name not in ['SKILL.md', 'LICENSE.txt']
        ]
        if names:
            target_res = [r for r in target_res if r.name in names]

        loaded = []
        for res in target_res:
            abs_path = res.path.resolve()
            loaded.append({
                'name': res.name,
                'file': res.to_dict(),
                'path': self._get_resource_path(res.path),
                'abs_path': str(abs_path),
                'content': self._read_file_content(abs_path),
            })
        self.resources.extend(loaded)
        return loaded

    def load_from_plan(self) -> None:
        """
        Load resources based on the execution plan.

        Loads only the scripts, references, and resources specified in the plan.
        """
        if self._resources_loaded or not self.plan:
            return

        if self.plan.required_scripts:
            self.load_scripts(self.plan.required_scripts)

        if self.plan.required_references:
            self.load_references(self.plan.required_references)

        if self.plan.required_resources:
            self.load_resources(self.plan.required_resources)

        self._resources_loaded = True

    def load_all(self) -> None:
        """Load all available resources (scripts, references, resources)."""
        if self._resources_loaded:
            return
        self.load_scripts()
        self.load_references()
        self.load_resources()
        self._resources_loaded = True

    def get_loaded_scripts_content(self) -> str:
        """Get formatted content of all loaded scripts."""
        if not self.scripts:
            return 'No scripts loaded.'
        parts = []
        for s in self.scripts:
            parts.append(f"<!-- {s['path']} -->\n{s['content']}")
        return '\n\n'.join(parts)

    def get_loaded_references_content(self) -> str:
        """Get formatted content of all loaded references."""
        if not self.references:
            return 'No references loaded.'
        parts = []
        for r in self.references:
            parts.append(f"<!-- {r['path']} -->\n{r['content']}")
        return '\n\n'.join(parts)

    def get_loaded_resources_content(self) -> str:
        """Get formatted content of all loaded resources."""
        if not self.resources:
            return 'No resources loaded.'
        parts = []
        for r in self.resources:
            parts.append(f"<!-- {r['path']} -->\n{r['content']}")
        return '\n\n'.join(parts)
