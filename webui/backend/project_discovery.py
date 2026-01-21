# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Project discovery module for MS-Agent Web UI
Discovers and manages available projects from the ms-agent/projects directory.
"""
import os
import re
from typing import Any, Dict, List, Optional


class ProjectDiscovery:
    """Discovers and manages projects from the ms-agent projects directory"""

    def __init__(self, projects_dir: str):
        self.projects_dir = projects_dir
        self._projects_cache: Optional[List[Dict[str, Any]]] = None

    def discover_projects(self,
                          force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Discover all available projects"""
        if self._projects_cache is not None and not force_refresh:
            return self._projects_cache

        projects = []

        if not os.path.exists(self.projects_dir):
            return projects

        for item in os.listdir(self.projects_dir):
            item_path = os.path.join(self.projects_dir, item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                project_info = self._analyze_project(item, item_path)
                if project_info:
                    projects.append(project_info)

        # Sort by display name
        projects.sort(key=lambda x: x['display_name'])
        self._projects_cache = projects
        return projects

    def _analyze_project(self, name: str,
                         path: str) -> Optional[Dict[str, Any]]:
        """Analyze a project directory and extract its information"""
        # Check for workflow.yaml or agent.yaml
        workflow_file = os.path.join(path, 'workflow.yaml')
        agent_file = os.path.join(path, 'agent.yaml')
        run_file = os.path.join(path, 'run.py')
        readme_file = os.path.join(path, 'README.md')

        # Determine project type
        if os.path.exists(workflow_file):
            project_type = 'workflow'
            config_file = workflow_file
        elif os.path.exists(agent_file):
            project_type = 'agent'
            config_file = agent_file
        elif os.path.exists(run_file):
            project_type = 'script'
            config_file = run_file
        else:
            # Skip directories without valid config
            return None

        # Generate display name from directory name
        display_name = self._format_display_name(name)

        # Extract description from README if available
        description = self._extract_description(readme_file) if os.path.exists(
            readme_file) else ''

        return {
            'id': name,
            'name': name,
            'display_name': display_name,
            'description': description,
            'type': project_type,
            'path': path,
            'has_readme': os.path.exists(readme_file),
            'config_file': config_file
        }

    def _format_display_name(self, name: str) -> str:
        """Convert directory name to display name"""
        # Replace underscores with spaces and title case
        display = name.replace('_', ' ').replace('-', ' ')
        # Handle camelCase
        display = re.sub(r'([a-z])([A-Z])', r'\1 \2', display)
        return display.title()

    def _extract_description(self, readme_path: str) -> str:
        """Extract first paragraph from README as description"""
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Skip title and find first paragraph
            lines = content.split('\n')
            description_lines = []
            in_description = False

            for line in lines:
                stripped = line.strip()
                # Skip headers and empty lines at the beginning
                if not in_description:
                    if stripped and not stripped.startswith(
                            '#') and not stripped.startswith('['):
                        in_description = True
                        description_lines.append(stripped)
                else:
                    if stripped and not stripped.startswith('#'):
                        description_lines.append(stripped)
                    elif not stripped and description_lines:
                        break

            description = ' '.join(description_lines)
            # Truncate if too long
            if len(description) > 300:
                description = description[:297] + '...'
            return description
        except Exception:
            return ''

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific project by ID"""
        projects = self.discover_projects()
        for project in projects:
            if project['id'] == project_id:
                return project
        return None

    def get_project_readme(self, project_id: str) -> Optional[str]:
        """Get the README content for a project"""
        project = self.get_project(project_id)
        if not project or not project['has_readme']:
            return None

        readme_path = os.path.join(project['path'], 'README.md')
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None

    def get_project_config(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get the configuration for a project"""
        project = self.get_project(project_id)
        if not project:
            return None

        try:
            import yaml
            with open(project['config_file'], 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception:
            return None
