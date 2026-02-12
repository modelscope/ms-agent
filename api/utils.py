# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Utility functions for API server
"""
import os
import json
from pathlib import Path
from typing import Any, Dict, Optional


def get_backend_root() -> Path:
    """Get the backend root directory"""
    return Path(__file__).resolve().parent


def get_session_work_dir(session_id: str) -> Path:
    """Get the working directory for a session"""
    if not session_id or not str(session_id).strip():
        raise ValueError('session_id is required')
    
    backend_root = get_backend_root()
    work_dir = (backend_root / 'work_dir' / str(session_id)).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def load_json_file(file_path: str) -> Optional[Dict[str, Any]]:
    """Load JSON from file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def save_json_file(file_path: str, data: Dict[str, Any]) -> bool:
    """Save JSON to file"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def ensure_dir(path: str) -> bool:
    """Ensure directory exists"""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def format_error_message(error: Exception) -> str:
    """Format error message for API response"""
    return f"{type(error).__name__}: {str(error)}"


def mask_sensitive_value(value: str, mask_char: str = "*") -> str:
    """Mask sensitive values like API keys"""
    if not value:
        return ""
    if len(value) <= 8:
        return mask_char * len(value)
    return value[:4] + mask_char * (len(value) - 8) + value[-4:]


def validate_session_id(session_id: str) -> bool:
    """Validate session ID format"""
    if not session_id or not isinstance(session_id, str):
        return False
    return len(session_id.strip()) > 0


def safe_json_loads(json_str: str, default: Any = None) -> Any:
    """Safely load JSON string with default fallback"""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def truncate_string(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """Truncate string to max length"""
    if not text or len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix
