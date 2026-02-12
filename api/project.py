# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Project management API endpoints
Handles project discovery, README retrieval, and project information
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .models import ProjectInfo, APIResponse

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


class ProjectDiscovery:
    """Discovers and manages projects from the ms-agent projects directory"""
    
    # Whitelist of projects to show in the UI
    VISIBLE_PROJECTS = {'code_genesis', 'singularity_cinema', 'deep_research', 'fin_research', 'doc_research'}
    
    def __init__(self, projects_dir: str):
        self.projects_dir = projects_dir
        self._projects_cache: Optional[List[Dict[str, Any]]] = None
    
    def discover_projects(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Discover all available projects"""
        if self._projects_cache is not None and not force_refresh:
            return self._projects_cache
        
        projects = []
        
        if not os.path.exists(self.projects_dir):
            return projects
        
        for item in os.listdir(self.projects_dir):
            item_path = os.path.join(self.projects_dir, item)
            # Only show projects in the whitelist
            if os.path.isdir(item_path) and not item.startswith('.') and item in self.VISIBLE_PROJECTS:
                project_info = self._analyze_project(item, item_path)
                if project_info:
                    projects.append(project_info)
        
        # Add virtual projects (non-top-level entries)
        projects.extend(self._build_virtual_projects())
        
        # Sort by display name
        projects.sort(key=lambda x: x['display_name'])
        self._projects_cache = projects
        return projects
    
    def _build_virtual_projects(self) -> List[Dict[str, Any]]:
        """Build virtual projects from subdirectories"""
        projects: List[Dict[str, Any]] = []
        
        # Deep Research V2
        v2_root = os.path.join(self.projects_dir, 'deep_research', 'v2')
        researcher_yaml = os.path.join(v2_root, 'researcher.yaml')
        if os.path.exists(researcher_yaml):
            readme_path = os.path.join(v2_root, 'README.md')
            description = self._extract_description(readme_path) if os.path.exists(readme_path) else ''
            projects.append({
                'id': 'deep_research_v2',
                'name': 'deep_research_v2',
                'display_name': 'Deep Research V2',
                'description': description,
                'type': 'agent',
                'path': v2_root,
                'has_readme': os.path.exists(readme_path),
                'config_file': researcher_yaml,
                'supports_workflow_switch': False
            })
        
        return projects
    
    def _analyze_project(self, name: str, path: str) -> Optional[Dict[str, Any]]:
        """Analyze a project directory and extract its information"""
        # Check for workflow.yaml or agent.yaml
        workflow_file = os.path.join(path, 'workflow.yaml')
        simple_workflow_file = os.path.join(path, 'simple_workflow.yaml')
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
        
        # Check if project supports workflow switching (e.g., code_genesis)
        supports_workflow_switch = False
        if project_type == 'workflow' and name == 'code_genesis' and os.path.exists(simple_workflow_file):
            supports_workflow_switch = True
        
        # Generate display name from directory name
        display_name = self._format_display_name(name)
        
        # Extract description from README if available
        description = self._extract_description(readme_file) if os.path.exists(readme_file) else ''
        
        return {
            'id': name,
            'name': name,
            'display_name': display_name,
            'description': description,
            'type': project_type,
            'path': path,
            'has_readme': os.path.exists(readme_file),
            'config_file': config_file,
            'supports_workflow_switch': supports_workflow_switch
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
                    if stripped and not stripped.startswith('#') and not stripped.startswith('['):
                        in_description = True
                        description_lines.append(stripped)
                else:
                    if stripped and not stripped.startswith('#'):
                        description_lines.append(stripped)
                    else:
                        break
                
                # Limit description length
                if len(' '.join(description_lines)) > 200:
                    break
            
            description = ' '.join(description_lines)
            if len(description) > 200:
                description = description[:197] + '...'
            
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
        """Get README content for a project"""
        project = self.get_project(project_id)
        if not project or not project.get('has_readme'):
            return None
        
        readme_path = os.path.join(project['path'], 'README.md')
        try:
            with open(readme_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return None


# Get projects directory
PROJECTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'projects')
project_discovery = ProjectDiscovery(PROJECTS_DIR)


# ============================================================
# API Endpoints
# ============================================================

@router.get("")
async def list_projects(force_refresh: bool = False):
    """List all available projects"""
    try:
        projects = project_discovery.discover_projects(force_refresh=force_refresh)
        return APIResponse(success=True, data=projects)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}")
async def get_project(project_id: str):
    """Get a specific project by ID"""
    try:
        project = project_discovery.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return APIResponse(success=True, data=project)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/readme")
async def get_project_readme(project_id: str):
    """Get README content for a project"""
    try:
        readme_content = project_discovery.get_project_readme(project_id)
        if readme_content is None:
            raise HTTPException(status_code=404, detail="README not found")
        
        return APIResponse(success=True, data={'content': readme_content})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/files/{file_path:path}")
async def get_project_file(project_id: str, file_path: str):
    """Get a file from a project directory"""
    try:
        project = project_discovery.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Construct absolute file path
        full_path = os.path.join(project['path'], file_path)
        
        # Security check: ensure the file is within the project directory
        if not os.path.abspath(full_path).startswith(os.path.abspath(project['path'])):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        
        return FileResponse(full_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project_id}/workflow")
async def get_project_workflow(project_id: str, session_id: Optional[str] = None):
    """Get the workflow configuration for a project
    
    If session_id is provided, returns the workflow based on the session's workflow_type.
    For code_genesis project, 'simple' workflow_type will return simple_workflow.yaml.
    """
    try:
        project = project_discovery.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Determine workflow_type from session if session_id is provided
        workflow_type = 'standard'  # default
        if session_id:
            # Import here to avoid circular dependency
            from .session import session_manager
            session = session_manager.get_session(session_id)
            if session and session.get('workflow_type'):
                workflow_type = session['workflow_type']
        
        # Determine which workflow file to use
        if workflow_type == 'simple' and project.get('supports_workflow_switch'):
            # For simple workflow, try simple_workflow.yaml first
            workflow_file = os.path.join(project['path'], 'simple_workflow.yaml')
            if not os.path.exists(workflow_file):
                # Fallback to standard workflow.yaml if simple_workflow.yaml doesn't exist
                workflow_file = os.path.join(project['path'], 'workflow.yaml')
        else:
            # Standard workflow
            workflow_file = os.path.join(project['path'], 'workflow.yaml')
        
        if not os.path.exists(workflow_file):
            raise HTTPException(status_code=404, detail="Workflow file not found")
        
        try:
            import yaml
            with open(workflow_file, 'r', encoding='utf-8') as f:
                workflow_data = yaml.safe_load(f)
            return APIResponse(
                success=True,
                data={'workflow': workflow_data, 'workflow_type': workflow_type}
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f'Error reading workflow file: {str(e)}'
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
