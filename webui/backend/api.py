# Copyright (c) Alibaba, Inc. and its affiliates.
"""
API endpoints for the MS-Agent Web UI
"""
import os
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
# Import shared instances
from shared import config_manager, project_discovery, session_manager

router = APIRouter()


def get_backend_root() -> Path:
    return Path(__file__).resolve().parents[1]  # equal to dirname(dirname(__file__))

def get_session_root(session_id: str) -> Path:
    if not session_id or not str(session_id).strip():
        raise HTTPException(status_code=400, detail="session_id is required")

    backend_root = get_backend_root()
    work_dir = (backend_root / "work_dir" / str(session_id)).resolve()
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


class SessionCreate(BaseModel):
    project_id: str
    query: Optional[str] = None


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
    print(f'project_discovery.discover_projects(): {project_discovery.discover_projects()}')
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


# Session Endpoints
@router.post('/sessions', response_model=SessionInfo)
async def create_session(session_data: SessionCreate):
    """Create a new session for a project"""
    project = project_discovery.get_project(session_data.project_id)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')

    session = session_manager.create_session(
        project_id=session_data.project_id, project_name=project['name'])
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
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    projects_dir = os.path.join(base_dir, 'ms-agent', 'projects')

    if session_id:

        session_root = get_session_root(session_id)
        resolved_root = (session_root / "").resolve()

    elif not root_dir or root_dir.strip() == "":
        resolved_root = output_dir
    else:
        root_dir = root_dir.strip()

        # If absolute, use as-is (but still must be within allowed_roots)
        if os.path.isabs(root_dir):
            resolved_root = root_dir
        else:
            # Try relative to output first, then projects
            cand1 = os.path.join(output_dir, root_dir)
            cand2 = os.path.join(projects_dir, root_dir)

            if os.path.exists(cand1):
                resolved_root = cand1
            elif os.path.exists(cand2):
                resolved_root = cand2
            else:
                # If user passes "output" or "projects" explicitly (common case)
                # allow interpreting it as those roots even if not exist check above
                if root_dir in ("output", "output/"):
                    resolved_root = output_dir
                elif root_dir in ("projects", "projects/"):
                    resolved_root = projects_dir
                else:
                    # fall back to output + root_dir (but it likely doesn't exist)
                    resolved_root = cand1

    resolved_root = os.path.normpath(os.path.abspath(resolved_root))

    # TODO: Security check: root must be within allowed roots

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
                    'abs_path': full_path,  # optional: if you still want absolute for debugging
                    'size': os.path.getsize(full_path),
                    'modified': os.path.getmtime(full_path)
                })

        result['files'].sort(key=lambda x: x['modified'], reverse=True)
        return result

    print("resolved_root =", resolved_root)
    tree = build_tree(resolved_root)
    return {'tree': tree, 'root_dir': resolved_root}

def get_allowed_roots():
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    output_dir = os.path.join(base_dir, 'ms-agent', 'output')
    projects_dir = os.path.join(base_dir, 'ms-agent', 'projects')
    return base_dir, os.path.normpath(output_dir), os.path.normpath(projects_dir)

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
    allowed_roots = [output_dir, projects_dir]

    if not root_dir or root_dir.strip() == "":
        resolved = output_dir
    else:
        rd = root_dir.strip()

        if os.path.isabs(rd):
            resolved = rd
        else:
            # Allow explicit "output"/"projects"
            if rd in ("output", "output/"):
                resolved = output_dir
            elif rd in ("projects", "projects/"):
                resolved = projects_dir
            else:
                cand1 = os.path.join(output_dir, rd)
                cand2 = os.path.join(projects_dir, rd)
                # choose existing one if possible, otherwise default to cand1
                resolved = cand1 if os.path.exists(cand1) else (cand2 if os.path.exists(cand2) else cand1)

    resolved = os.path.normpath(os.path.abspath(resolved))

    # Security: resolved root must be within allowed roots
    def within(child: str, parent: str) -> bool:
        parent = os.path.normpath(os.path.abspath(parent))
        child = os.path.normpath(os.path.abspath(child))
        return child == parent or child.startswith(parent + os.sep)

    # TODO: security dir check

    return resolved

def resolve_file_path(root_dir_abs: str, file_path: str) -> str:
    """
    Resolve file_path against root_dir_abs.
    - if file_path is absolute, require it's within root_dir_abs
    - if relative, join(root_dir_abs, file_path)
    """
    root_dir_abs = os.path.normpath(os.path.abspath(root_dir_abs))

    if os.path.isabs(file_path):
        full_path = os.path.normpath(os.path.abspath(file_path))
    else:
        full_path = os.path.normpath(os.path.abspath(os.path.join(root_dir_abs, file_path)))

    # TODO: Security: file must be within root_dir_abs

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
        raise HTTPException(status_code=404, detail=f'File not found: {full_path}')

    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail=f'Path {full_path} is not a file')
    # limit 1MB
    file_size = os.path.getsize(full_path)
    if file_size > 1024 * 1024:
        raise HTTPException(status_code=400, detail='File too large (max 1MB)')

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        ext = os.path.splitext(full_path)[1].lower()
        lang_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'typescript',
            '.jsx': 'javascript', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
            '.md': 'markdown', '.html': 'html', '.css': 'css', '.txt': 'text',
            '.sh': 'bash', '.java': 'java', '.go': 'go', '.rs': 'rust',
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
        raise HTTPException(status_code=500, detail=f'Error reading file: {str(e)}')

def resolve_and_check_path(file_path: str) -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    output_dir = os.path.join(base_dir, 'ms-agent', 'output')
    projects_dir = os.path.join(base_dir, 'ms-agent', 'projects')

    if not os.path.isabs(file_path):
        full_path = os.path.join(output_dir, file_path)
        if not os.path.exists(full_path):
            full_path = os.path.join(projects_dir, file_path)
    else:
        full_path = file_path

    full_path = os.path.normpath(full_path)

    # TODO: security path check

    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f'File not found: {full_path}')
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=400, detail=f'Path {full_path} is not a file')

    return full_path


@router.get("/files/stream")
async def stream_file(path: str, session_id: Optional[str] = Query(default=None)):
    if session_id:
        session_root = get_session_root(session_id)
        root_abs = str(session_root.resolve())
        full_path = resolve_file_path(root_abs, path)
    else:
        full_path = resolve_and_check_path(path)

    media_type, _ = mimetypes.guess_type(full_path)
    media_type = media_type or "application/octet-stream"
    return FileResponse(
        full_path,
        media_type=media_type,
        filename=os.path.basename(full_path),
        headers={"Content-Disposition": f'inline; filename="{os.path.basename(full_path)}"'},
    )