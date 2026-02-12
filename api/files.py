# Copyright (c) Alibaba, Inc. and its affiliates.
"""
File operations API endpoints
Handles file listing, reading, and streaming
"""
import os
import mimetypes
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .models import APIResponse

router = APIRouter(prefix="/api/v1/files", tags=["files"])


class FileReadRequest(BaseModel):
    """Request model for reading a file"""
    path: str
    session_id: Optional[str] = None
    root_dir: Optional[str] = None


def get_session_root(session_id: str) -> Path:
    """Get the work directory for a session"""
    if not session_id or not str(session_id).strip():
        raise HTTPException(status_code=400, detail='session_id is required')
    
    # Get the API root directory
    api_root = Path(__file__).resolve().parent
    work_dir = (api_root / 'work_dir' / str(session_id)).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def get_allowed_roots():
    """Get allowed root directories for file access"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, 'output')
    projects_dir = os.path.join(base_dir, 'projects')
    return base_dir, os.path.normpath(output_dir), os.path.normpath(projects_dir)


def resolve_root_dir(root_dir: Optional[str], session_id: Optional[str] = None) -> str:
    """
    Resolve optional root_dir to an absolute normalized path within allowed roots.
    Default: output_dir
    Supports:
      - None/"" => output_dir
      - "output", "projects", "projects/xxx"
      - absolute path (must still be under allowed roots)
    """
    if session_id:
        session_root = get_session_root(session_id)
        return str(session_root.resolve())
    
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
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.normpath(
            os.path.abspath(os.path.join(base_dir, file_path)))
    else:
        # Try multiple locations
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        candidates = [
            # First try with root_dir_abs (for session-based access)
            os.path.join(root_dir_abs, file_path),
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
    
    # TODO: Security check: ensure `full_path` is within configured allowed roots.
    
    return full_path


@router.get("/list")
async def list_files(
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
    
    resolved_root = resolve_root_dir(root_dir or output_dir, session_id)
    
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
                # Return RELATIVE path to resolved_root
                rel_path = os.path.relpath(full_path, resolved_root)
                
                result['files'].append({
                    'name': item,
                    'path': rel_path,
                    'abs_path': full_path,
                    'size': os.path.getsize(full_path),
                    'modified': os.path.getmtime(full_path)
                })
        
        result['files'].sort(key=lambda x: x['modified'], reverse=True)
        return result
    
    tree = build_tree(resolved_root)
    return APIResponse(
        success=True,
        data={'tree': tree, 'root_dir': resolved_root}
    )


@router.post("/read")
async def read_file(request: FileReadRequest):
    """Read file content"""
    try:
        root_abs = resolve_root_dir(request.root_dir, request.session_id)
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
            
            # Return a relative path (relative to root_dir)
            rel_path = os.path.relpath(full_path, root_abs)
            
            return APIResponse(
                success=True,
                data={
                    'content': content,
                    'path': rel_path,
                    'abs_path': full_path,
                    'root_dir': root_abs,
                    'filename': os.path.basename(full_path),
                    'language': language,
                    'size': file_size
                }
            )
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail='File is not a text file')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f'Error reading file: {str(e)}')


@router.get("/stream")
async def stream_file(
    path: str,
    session_id: Optional[str] = Query(default=None),
    root_dir: Optional[str] = Query(default=None)
):
    """Stream file for download or preview"""
    try:
        if session_id:
            session_root = get_session_root(session_id)
            root_abs = str(session_root.resolve())
            full_path = resolve_file_path(root_abs, path)
        else:
            root_abs = resolve_root_dir(root_dir)
            full_path = resolve_file_path(root_abs, path)
        
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail='File not found')
        
        if not os.path.isfile(full_path):
            raise HTTPException(status_code=400, detail='Path is not a file')
        
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
