# Copyright (c) Alibaba, Inc. and its affiliates.
"""
API endpoints for the MS-Agent Web UI
"""
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
# Import shared instances
from shared import config_manager, project_discovery, session_manager

router = APIRouter()


# Request/Response Models
class ProjectInfo(BaseModel):
    id: str
    name: str
    display_name: str
    description: str
    type: str  # 'workflow' or 'agent'
    path: str
    has_readme: bool
    supports_workflow_switch: bool = False


class SessionCreate(BaseModel):
    project_id: str
    query: Optional[str] = None
    workflow_type: Optional[
        str] = 'standard'  # 'standard' or 'simple' for code_genesis


class SessionInfo(BaseModel):
    id: str
    project_id: str
    project_name: str
    status: str
    created_at: str


class LLMConfig(BaseModel):
    provider: str = 'openai'
    model: str = 'qwen3-coder-plus'
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096


class EditFileConfig(BaseModel):
    api_key: Optional[str] = None
    base_url: str = 'https://api.morphllm.com/v1'
    diff_model: str = 'morph-v3-fast'


class EdgeOnePagesConfig(BaseModel):
    api_token: Optional[str] = None
    project_name: Optional[str] = None


class MCPServer(BaseModel):
    name: str
    type: str  # 'stdio' or 'sse'
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None


class GlobalConfig(BaseModel):
    llm: LLMConfig
    mcp_servers: Dict[str, Any]
    theme: str = 'dark'
    output_dir: str = './output'


# Project Endpoints
@router.get('/projects', response_model=List[ProjectInfo])
async def list_projects():
    """List all available projects"""
    return project_discovery.discover_projects()


@router.get('/projects/{project_id}')
async def get_project(project_id: str):
    """Get detailed information about a specific project"""
    project = project_discovery.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    return project


@router.get('/projects/{project_id}/readme')
async def get_project_readme(project_id: str):
    """Get the README content for a project"""
    readme = project_discovery.get_project_readme(project_id)
    if readme is None:
        raise HTTPException(status_code=404, detail='README not found')
    return {'content': readme}


@router.get('/projects/{project_id}/workflow')
async def get_project_workflow(project_id: str,
                               session_id: Optional[str] = None):
    """Get the workflow configuration for a project

    If session_id is provided, returns the workflow based on the session's workflow_type.
    For code_genesis project, 'simple' workflow_type will return simple_workflow.yaml.
    """
    project = project_discovery.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')

    # Determine workflow_type from session if session_id is provided
    workflow_type = 'standard'  # default
    if session_id:
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
        raise HTTPException(status_code=404, detail='Workflow file not found')

    try:
        import yaml
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow_data = yaml.safe_load(f)
        return {'workflow': workflow_data, 'workflow_type': workflow_type}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error reading workflow file: {str(e)}')


# Session Endpoints
@router.post('/sessions', response_model=SessionInfo)
async def create_session(session_data: SessionCreate):
    """Create a new session for a project"""
    project = project_discovery.get_project(session_data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')

    # Validate workflow_type for projects that support switching
    workflow_type = session_data.workflow_type or 'standard'
    if project.get('supports_workflow_switch'):
        if workflow_type not in ['standard', 'simple']:
            raise HTTPException(
                status_code=400,
                detail="workflow_type must be 'standard' or 'simple'")

    session = session_manager.create_session(
        project_id=session_data.project_id,
        project_name=project['name'],
        workflow_type=workflow_type)
    return session


@router.get('/sessions', response_model=List[SessionInfo])
async def list_sessions():
    """List all active sessions"""
    return session_manager.list_sessions()


@router.get('/sessions/{session_id}')
async def get_session(session_id: str):
    """Get session details"""
    session = session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return session


@router.delete('/sessions/{session_id}')
async def delete_session(session_id: str):
    """Delete a session"""
    success = session_manager.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'status': 'deleted'}


@router.get('/sessions/{session_id}/messages')
async def get_session_messages(session_id: str):
    """Get all messages for a session"""
    messages = session_manager.get_messages(session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'messages': messages}


# Configuration Endpoints
@router.get('/config')
async def get_config():
    """Get global configuration"""
    return config_manager.get_config()


@router.put('/config')
async def update_config(config: GlobalConfig):
    """Update global configuration"""
    config_manager.update_config(config.model_dump())
    return {'status': 'updated'}


@router.get('/config/llm')
async def get_llm_config():
    """Get LLM configuration"""
    return config_manager.get_llm_config()


@router.put('/config/llm')
async def update_llm_config(config: LLMConfig):
    """Update LLM configuration"""
    config_manager.update_llm_config(config.model_dump())
    return {'status': 'updated'}


@router.get('/config/mcp')
async def get_mcp_config():
    """Get MCP servers configuration"""
    return config_manager.get_mcp_config()


@router.put('/config/mcp')
async def update_mcp_config(servers: Dict[str, Any]):
    """Update MCP servers configuration"""
    config_manager.update_mcp_config(servers)
    return {'status': 'updated'}


@router.get('/config/edit_file')
async def get_edit_file_config():
    """Get edit_file_config configuration"""
    return config_manager.get_edit_file_config()


@router.put('/config/edit_file')
async def update_edit_file_config(config: EditFileConfig):
    """Update edit_file_config configuration"""
    config_manager.update_edit_file_config(config.model_dump())
    return {'status': 'updated'}


@router.get('/config/edgeone_pages')
async def get_edgeone_pages_config():
    """Get EdgeOne Pages configuration"""
    return config_manager.get_edgeone_pages_config()


@router.put('/config/edgeone_pages')
async def update_edgeone_pages_config(config: EdgeOnePagesConfig):
    """Update EdgeOne Pages configuration"""
    config_manager.update_edgeone_pages_config(config.model_dump())
    return {'status': 'updated'}


@router.post('/config/mcp/servers')
async def add_mcp_server(server: MCPServer):
    """Add a new MCP server"""
    config_manager.add_mcp_server(server.name,
                                  server.model_dump(exclude={'name'}))
    return {'status': 'added'}


@router.delete('/config/mcp/servers/{server_name}')
async def remove_mcp_server(server_name: str):
    """Remove an MCP server"""
    success = config_manager.remove_mcp_server(server_name)
    if not success:
        raise HTTPException(status_code=404, detail='Server not found')
    return {'status': 'removed'}


# Available models endpoint
@router.get('/models')
async def list_available_models():
    """List available LLM models"""
    return {
        'models': [
            {
                'provider': 'modelscope',
                'model': 'Qwen/Qwen3-235B-A22B-Instruct-2507',
                'display_name': 'Qwen3-235B (Recommended)'
            },
            {
                'provider': 'modelscope',
                'model': 'Qwen/Qwen2.5-72B-Instruct',
                'display_name': 'Qwen2.5-72B'
            },
            {
                'provider': 'modelscope',
                'model': 'Qwen/Qwen2.5-32B-Instruct',
                'display_name': 'Qwen2.5-32B'
            },
            {
                'provider': 'modelscope',
                'model': 'deepseek-ai/DeepSeek-V3',
                'display_name': 'DeepSeek-V3'
            },
            {
                'provider': 'openai',
                'model': 'gpt-4o',
                'display_name': 'GPT-4o'
            },
            {
                'provider': 'openai',
                'model': 'gpt-4o-mini',
                'display_name': 'GPT-4o Mini'
            },
            {
                'provider': 'anthropic',
                'model': 'claude-3-5-sonnet-20241022',
                'display_name': 'Claude 3.5 Sonnet'
            },
        ]
    }


# File content endpoint
class FileReadRequest(BaseModel):
    path: str
    session_id: Optional[str] = None


@router.get('/files/list')
async def list_output_files():
    """List all files in the output directory as a tree structure"""
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_dir = os.path.join(base_dir, 'output')

    # Folders to exclude
    exclude_dirs = {
        'node_modules', '__pycache__', '.git', '.venv', 'venv', 'dist', 'build'
    }

    def build_tree(dir_path: str) -> dict:
        """Recursively build a tree structure"""
        result = {'folders': {}, 'files': []}

        if not os.path.exists(dir_path):
            return result

        try:
            items = os.listdir(dir_path)
        except PermissionError:
            return result

        for item in sorted(items):
            # Skip hidden files/folders and excluded directories
            if item.startswith('.') or item in exclude_dirs:
                continue

            full_path = os.path.join(dir_path, item)

            if os.path.isdir(full_path):
                # Recursively build subtree
                subtree = build_tree(full_path)
                # Only include folder if it has content
                if subtree['folders'] or subtree['files']:
                    result['folders'][item] = subtree
            else:
                result['files'].append({
                    'name': item,
                    'path': full_path,
                    'size': os.path.getsize(full_path),
                    'modified': os.path.getmtime(full_path)
                })

        # Sort files by modification time (newest first)
        result['files'].sort(key=lambda x: x['modified'], reverse=True)

        return result

    tree = build_tree(output_dir)
    return {'tree': tree, 'output_dir': output_dir}


@router.post('/files/read')
async def read_file_content(request: FileReadRequest):
    """Read content of a generated file"""
    file_path = request.path

    # Get base directories for security check
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_dir = os.path.join(base_dir, 'output')
    projects_dir = os.path.join(base_dir, 'projects')

    print(f'[API] Reading file: {file_path}')
    print(f'[API] Output dir: {output_dir}')
    print(f'[API] Projects dir: {projects_dir}')

    # Normalize the input path
    file_path = file_path.strip()

    # Try multiple path resolution strategies
    candidate_paths = []

    if os.path.isabs(file_path):
        # Absolute path - use as-is (but still check security)
        candidate_paths.append(file_path)
    else:
        # Relative path - try different combinations
        # Remove leading slashes
        normalized = file_path.lstrip('/')

        # Strategy 1: Path already contains output/ or projects/ prefix
        if normalized.startswith('output/'):
            # Remove 'output/' prefix and try in output_dir
            candidate_paths.append(os.path.join(output_dir, normalized[7:]))
            # Also try in project-specific output directories
            if os.path.exists(projects_dir):
                try:
                    for project_name in os.listdir(projects_dir):
                        project_path = os.path.join(projects_dir, project_name)
                        if os.path.isdir(project_path):
                            project_output = os.path.join(
                                project_path, 'output')
                            if os.path.exists(project_output):
                                candidate_paths.append(
                                    os.path.join(project_output,
                                                 normalized[7:]))
                except (OSError, PermissionError):
                    pass  # Skip if can't list directory
        elif normalized.startswith('projects/'):
            # Remove 'projects/' prefix and try in projects_dir
            candidate_paths.append(os.path.join(projects_dir, normalized[9:]))
        else:
            # Strategy 2: Try as-is in output dir (most common case)
            candidate_paths.append(os.path.join(output_dir, normalized))
            # Strategy 3: Try as-is in projects dir
            candidate_paths.append(os.path.join(projects_dir, normalized))
            # Strategy 4: Try in project-specific output directories
            if os.path.exists(projects_dir):
                try:
                    for project_name in os.listdir(projects_dir):
                        project_path = os.path.join(projects_dir, project_name)
                        if os.path.isdir(project_path):
                            project_output = os.path.join(
                                project_path, 'output')
                            if os.path.exists(project_output):
                                candidate_paths.append(
                                    os.path.join(project_output, normalized))
                                # Strategy 4a: Try converting hyphenated names to directory structure
                                # e.g., "css-style.css" -> "css/style.css"
                                if '-' in normalized and '.' in normalized:
                                    parts = normalized.rsplit('.', 1)
                                    if len(parts) == 2:
                                        name, ext = parts
                                        # Try splitting on first hyphen: "css-style" -> "css/style"
                                        if '-' in name:
                                            dir_name, file_name = name.split(
                                                '-', 1)
                                            alt_path = os.path.join(
                                                project_output, dir_name,
                                                f'{file_name}.{ext}')
                                            candidate_paths.append(alt_path)
                except (OSError, PermissionError):
                    pass  # Skip if can't list directory

        # Strategy 5: Try original path (with leading slash) in both directories
        if file_path != normalized:
            candidate_paths.append(os.path.join(output_dir, file_path))
            candidate_paths.append(os.path.join(projects_dir, file_path))
            # Also try in project-specific output directories
            if os.path.exists(projects_dir):
                try:
                    for project_name in os.listdir(projects_dir):
                        project_path = os.path.join(projects_dir, project_name)
                        if os.path.isdir(project_path):
                            project_output = os.path.join(
                                project_path, 'output')
                            if os.path.exists(project_output):
                                candidate_paths.append(
                                    os.path.join(project_output, file_path))
                except (OSError, PermissionError):
                    pass  # Skip if can't list directory

    # Find the first existing file
    full_path = None
    for candidate in candidate_paths:
        normalized_candidate = os.path.normpath(candidate)
        # Security check: ensure file is within allowed directories
        allowed_dirs = [
            os.path.normpath(output_dir),
            os.path.normpath(projects_dir)
        ]
        is_allowed = any(
            normalized_candidate.startswith(d) for d in allowed_dirs)

        if is_allowed and os.path.exists(
                normalized_candidate) and os.path.isfile(normalized_candidate):
            full_path = normalized_candidate
            print(f'[API] Found file at: {full_path}')
            break
        else:
            if len(candidate_paths) <= 10:  # Only print if not too many paths
                exists = os.path.exists(normalized_candidate)
                print(f'[API] Tried: {normalized_candidate} '
                      f'(exists: {exists}, allowed: {is_allowed})')

    if not full_path:
        # Provide detailed error message
        tried_paths = '\n'.join(
            [f'  - {os.path.normpath(p)}' for p in candidate_paths])
        error_msg = f'File not found: {file_path}\nTried paths:\n{tried_paths}'
        print(f'[API] {error_msg}')
        raise HTTPException(status_code=404, detail=error_msg)

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail='Path is not a file')

    # Check file size (limit to 1MB)
    file_size = os.path.getsize(full_path)
    if file_size > 1024 * 1024:
        raise HTTPException(status_code=400, detail='File too large (max 1MB)')

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Detect language from extension
        ext = os.path.splitext(full_path)[1].lower()
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.jsx': 'javascript',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
            '.html': 'html',
            '.css': 'css',
            '.txt': 'text',
            '.sh': 'bash',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
        }
        language = lang_map.get(ext, 'text')

        return {
            'content': content,
            'path': full_path,
            'filename': os.path.basename(full_path),
            'language': language,
            'size': file_size
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail='File is not a text file')
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error reading file: {str(e)}')
