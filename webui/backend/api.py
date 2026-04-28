# Copyright (c) Alibaba, Inc. and its affiliates.
"""
API endpoints for the MS-Agent Web UI
"""
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
# Import shared instances
from shared import config_manager, project_discovery, session_manager

router = APIRouter()


def get_backend_root() -> Path:
    return Path(__file__).resolve().parents[
        1]  # equal to dirname(dirname(__file__))


def get_session_root(session_id: str) -> Path:
    if not session_id or not str(session_id).strip():
        raise HTTPException(status_code=400, detail='session_id is required')

    backend_root = get_backend_root()
    work_dir = (backend_root / 'work_dir' / str(session_id)).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


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
    project_id: Optional[str] = None  # Optional for chat mode
    query: Optional[str] = None
    workflow_type: Optional[
        str] = 'standard'  # 'standard' or 'simple' for code_genesis
    session_type: Optional[str] = 'project'  # 'project' or 'chat'


class SessionInfo(BaseModel):
    id: str
    project_id: str
    project_name: str
    status: str
    created_at: str
    session_type: Optional[str] = 'project'  # 'project' or 'chat'


class LLMConfig(BaseModel):
    provider: str = 'openai'
    model: str = 'qwen3-coder-plus'
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    temperature_enabled: Optional[bool] = False
    max_tokens: Optional[int] = None


class EditFileConfig(BaseModel):
    api_key: Optional[str] = None
    base_url: str = 'https://api.morphllm.com/v1'
    diff_model: str = 'morph-v3-fast'


class EdgeOnePagesConfig(BaseModel):
    api_token: Optional[str] = None
    project_name: Optional[str] = None


class SearchKeysConfig(BaseModel):
    exa_api_key: Optional[str] = None
    serpapi_api_key: Optional[str] = None


class DeepResearchAgentConfig(BaseModel):
    model: Optional[str] = ''
    api_key: Optional[str] = ''
    base_url: Optional[str] = ''


class DeepResearchSearchConfig(BaseModel):
    summarizer_model: Optional[str] = ''
    summarizer_api_key: Optional[str] = ''
    summarizer_base_url: Optional[str] = ''


class DeepResearchConfig(BaseModel):
    researcher: DeepResearchAgentConfig = Field(
        default_factory=DeepResearchAgentConfig)
    searcher: DeepResearchAgentConfig = Field(
        default_factory=DeepResearchAgentConfig)
    reporter: DeepResearchAgentConfig = Field(
        default_factory=DeepResearchAgentConfig)
    search: DeepResearchSearchConfig = Field(
        default_factory=DeepResearchSearchConfig)


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
    print(
        f'project_discovery.discover_projects(): {project_discovery.discover_projects()}'
    )
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
    """Create a new session for a project or chat mode"""
    # Check if this is a chat mode session
    if session_data.session_type == 'chat':
        # Create chat session without requiring a project
        session = session_manager.create_session(
            project_id='__chat__',
            project_name='Chat Assistant',
            workflow_type='standard',
            session_type='chat')
        return session

    # For project mode, validate project exists
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
        workflow_type=workflow_type,
        session_type='project')
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


@router.get('/sessions/{session_id}/dr_events')
async def get_session_dr_events(session_id: str,
                                after_id: Optional[int] = Query(None, ge=0)):
    """Get deep research event history for a session."""
    events = session_manager.list_dr_events(session_id, after_id)
    if events is None:
        raise HTTPException(status_code=404, detail='Session not found')
    return {'events': events}


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


@router.get('/config/search_keys')
async def get_search_keys_config():
    """Get search API keys configuration"""
    return config_manager.get_search_keys()


@router.put('/config/search_keys')
async def update_search_keys_config(config: SearchKeysConfig):
    """Update search API keys configuration"""
    config_manager.update_search_keys(config.model_dump())
    return {'status': 'updated'}


@router.get('/config/deep_research')
async def get_deep_research_config():
    """Get deep research configuration"""
    return config_manager.get_deep_research_config()


@router.put('/config/deep_research')
async def update_deep_research_config(config: DeepResearchConfig):
    """Update deep research configuration"""
    config_manager.update_deep_research_config(config.model_dump())
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
    root_dir: Optional[str] = None


@router.get('/files/list')
async def list_output_files(
        output_dir: Optional[str] = Query(default='output'),
        session_id: Optional[str] = Query(default=None),
        root_dir: Optional[str] = Query(default=None),
):
    """List all files under root_dir as a tree structure.
    root_dir: optional. If not provided, defaults to ms-agent/output.
              Also supports 'projects' or 'projects/xxx' etc.
    """
    # Excluded folders
    exclude_dirs = {
        'node_modules', '__pycache__', '.git', '.venv', 'venv', 'dist', 'build'
    }

    # Base directories (same way as read_file_content)
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    projects_dir = os.path.join(base_dir, 'projects')

    if session_id:

        session_root = get_session_root(session_id)
        resolved_root = (session_root / '').resolve()

    elif not root_dir or root_dir.strip() == '':
        resolved_root = output_dir
    else:
        root_dir = root_dir.strip()

        # If absolute, use as-is
        if os.path.isabs(root_dir):
            resolved_root = root_dir
        # If starts with 'projects/', join with base_dir
        elif root_dir.startswith('projects/'):
            resolved_root = os.path.join(base_dir, root_dir)
        else:
            # Try relative to output first, then projects
            cand1 = os.path.join(output_dir, root_dir)
            cand2 = os.path.join(projects_dir, root_dir)

            if os.path.exists(cand1):
                resolved_root = cand1
            elif os.path.exists(cand2):
                resolved_root = cand2
            else:
                # If user passes "output" or "projects" explicitly
                if root_dir in ('output', 'output/'):
                    resolved_root = output_dir
                elif root_dir in ('projects', 'projects/'):
                    resolved_root = projects_dir
                else:
                    # fall back to output + root_dir (but it likely doesn't exist)
                    resolved_root = cand1

    resolved_root = os.path.normpath(os.path.abspath(resolved_root))

    # Warning: Web UI is for local-only convenience (frontend/backend assumed localhost).
    # For production, enforce strict backend file-access validation and authorization
    # to prevent arbitrary path read/write (e.g., path traversal).
    # TODO: Security check: ensure `resolved_root` is within configured allowed roots.

    def build_tree(dir_path: str) -> dict:
        result = {'folders': {}, 'files': []}

        if not os.path.exists(dir_path):
            return result

        try:
            items = os.listdir(dir_path)
        except PermissionError:
            return result

        for item in sorted(items):
            if item.startswith('.') or item in exclude_dirs:
                continue

            full_path = os.path.join(dir_path, item)

            if os.path.isdir(full_path):
                subtree = build_tree(full_path)
                if subtree['folders'] or subtree['files']:
                    result['folders'][item] = subtree
            else:
                # Return RELATIVE path to resolved_root (better for frontend + read API)
                rel_path = os.path.relpath(full_path, resolved_root)

                result['files'].append({
                    'name': item,
                    'path': rel_path,  # <-- relative path
                    'abs_path':
                    full_path,  # optional: if you still want absolute for debugging
                    'size': os.path.getsize(full_path),
                    'modified': os.path.getmtime(full_path)
                })

        result['files'].sort(key=lambda x: x['modified'], reverse=True)
        return result

    print('resolved_root =', resolved_root)
    tree = build_tree(resolved_root)
    return {'tree': tree, 'root_dir': resolved_root}


def get_allowed_roots():
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_dir = os.path.join(base_dir, 'output')
    projects_dir = os.path.join(base_dir, 'projects')
    return base_dir, os.path.normpath(output_dir), os.path.normpath(
        projects_dir)


def resolve_root_dir(root_dir: Optional[str]) -> str:
    """
    Resolve optional root_dir to an absolute normalized path within allowed roots.
    Default: output_dir
    Supports:
      - None/"" => output_dir
      - "output", "projects", "projects/xxx"
      - absolute path (must still be under allowed roots)
    """
    _, output_dir, projects_dir = get_allowed_roots()

    if not root_dir or root_dir.strip() == '':
        resolved = output_dir
    else:
        rd = root_dir.strip()

        if os.path.isabs(rd):
            resolved = rd
        else:
            # Allow explicit "output"/"projects"
            if rd in ('output', 'output/'):
                resolved = output_dir
            elif rd in ('projects', 'projects/'):
                resolved = projects_dir
            else:
                cand1 = os.path.join(output_dir, rd)
                cand2 = os.path.join(projects_dir, rd)
                # choose existing one if possible, otherwise default to cand1
                resolved = cand1 if os.path.exists(cand1) else (
                    cand2 if os.path.exists(cand2) else cand1)

    resolved = os.path.normpath(os.path.abspath(resolved))

    # Warning: Web UI is for local-only convenience (frontend/backend assumed localhost).
    # For production, enforce strict backend file-access validation and authorization
    # to prevent arbitrary path read/write (e.g., path traversal).
    # TODO: Security check: ensure `resolved` is within configured allowed roots.

    return resolved


def resolve_file_path(root_dir_abs: str, file_path: str) -> str:
    """
    Resolve file_path against root_dir_abs.
    - if file_path starts with 'projects/', resolve from ms-agent base dir
    - if file_path is absolute, use as-is
    - if relative, join(root_dir_abs, file_path)
    """
    root_dir_abs = os.path.normpath(os.path.abspath(root_dir_abs))

    if os.path.isabs(file_path):
        full_path = os.path.normpath(os.path.abspath(file_path))
    elif file_path.startswith('projects/'):
        # Special case: if path starts with 'projects/', resolve from base_dir
        # This handles: projects/code_genesis/output/config.js
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        full_path = os.path.normpath(
            os.path.abspath(os.path.join(base_dir, file_path)))
    else:
        # Try multiple locations
        base_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        candidates = [
            # First try with root_dir_abs (for session-based access)
            os.path.join(root_dir_abs, file_path),
            # Then try in each project's output directory
        ]

        # Search in project output directories
        projects_dir = os.path.join(base_dir, 'projects')
        if os.path.exists(projects_dir):
            try:
                for project_name in os.listdir(projects_dir):
                    project_path = os.path.join(projects_dir, project_name)
                    if os.path.isdir(project_path):
                        candidates.append(
                            os.path.join(project_path, 'output', file_path))
            except (OSError, PermissionError):
                pass

        # Find first existing file
        full_path = None
        for candidate in candidates:
            candidate = os.path.normpath(candidate)
            if os.path.exists(candidate) and os.path.isfile(candidate):
                full_path = candidate
                break

        if not full_path:
            # Default to first candidate if none found
            full_path = os.path.normpath(candidates[0])

    # Warning: Web UI is for local-only convenience (frontend/backend assumed localhost).
    # For production, enforce strict backend file-access validation and authorization
    # to prevent arbitrary path read/write (e.g., path traversal).
    # TODO: Security check: ensure `full_path` is within configured allowed roots.

    return full_path


@router.post('/files/read')
async def read_file_content(request: FileReadRequest):
    if request.session_id:
        session_root = get_session_root(request.session_id)
        root_abs = os.path.normpath(os.path.abspath(str(session_root)))
    else:
        root_abs = resolve_root_dir(request.root_dir)
    full_path = resolve_file_path(root_abs, request.path)

    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=404, detail=f'File not found: {full_path}')

    if not os.path.isfile(full_path):
        raise HTTPException(
            status_code=400, detail=f'Path {full_path} is not a file')
    # limit 1MB
    file_size = os.path.getsize(full_path)
    if file_size > 1024 * 1024:
        raise HTTPException(status_code=400, detail='File too large (max 1MB)')

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

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

        # Return a relative path (relative to root_dir) for consistent handling on the frontend.
        rel_path = os.path.relpath(full_path, root_abs)

        return {
            'content': content,
            'path': rel_path,
            'abs_path': full_path,
            'root_dir': root_abs,
            'filename': os.path.basename(full_path),
            'language': language,
            'size': file_size
        }
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail='File is not a text file')
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error reading file: {str(e)}')


def resolve_and_check_path(file_path: str) -> str:
    """Resolve file path, trying multiple locations"""
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    if os.path.isabs(file_path):
        full_path = file_path
    else:
        # Smart path resolution:
        # If path already starts with 'projects/', use it directly under base_dir
        # Otherwise try output_dir first, then search in project outputs

        candidates = []

        # If path starts with 'projects/', join directly with base_dir
        if file_path.startswith('projects/'):
            candidates.append(os.path.join(base_dir, file_path))
        else:
            # Try base_dir/output first
            output_dir = os.path.join(base_dir, 'output')
            candidates.append(os.path.join(output_dir, file_path))

            # Try base_dir directly
            candidates.append(os.path.join(base_dir, file_path))

            # Search in each project's output directory
            projects_dir = os.path.join(base_dir, 'projects')
            if os.path.exists(projects_dir):
                try:
                    for project_name in os.listdir(projects_dir):
                        project_path = os.path.join(projects_dir, project_name)
                        if os.path.isdir(project_path):
                            # Try project/output/filename
                            candidates.append(
                                os.path.join(project_path, 'output',
                                             file_path))
                except (OSError, PermissionError):
                    pass

        # Find first existing file
        full_path = None
        for candidate in candidates:
            candidate = os.path.normpath(candidate)
            if os.path.exists(candidate) and os.path.isfile(candidate):
                full_path = candidate
                break

        if not full_path:
            # If not found, use the first candidate for error message
            full_path = os.path.normpath(
                candidates[0] if candidates else file_path)

    full_path = os.path.normpath(full_path)

    # Warning: Web UI is for local-only convenience (frontend/backend assumed localhost).
    # For production, enforce strict backend file-access validation and authorization
    # to prevent arbitrary path read/write (e.g., path traversal).
    # TODO: Security check: ensure `full_path` is within configured allowed roots.

    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=404, detail=f'File not found: {full_path}')
    if not os.path.isfile(full_path):
        raise HTTPException(
            status_code=400, detail=f'Path {full_path} is not a file')

    return full_path


@router.get('/files/stream')
async def stream_file(path: str,
                      session_id: Optional[str] = Query(default=None)):
    if session_id:
        session_root = get_session_root(session_id)
        root_abs = str(session_root.resolve())
        full_path = resolve_file_path(root_abs, path)
    else:
        full_path = resolve_and_check_path(path)

    media_type, _ = mimetypes.guess_type(full_path)
    media_type = media_type or 'application/octet-stream'
    return FileResponse(
        full_path,
        media_type=media_type,
        filename=os.path.basename(full_path),
        headers={
            'Content-Disposition':
            f'inline; filename="{os.path.basename(full_path)}"'
        },
    )
