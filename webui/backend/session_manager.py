# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Session management for MS-Agent Web UI
Handles session lifecycle and message history.
"""
import uuid
from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional


class SessionManager:
    """Manages user sessions and their message history"""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = Lock()

    def create_session(self,
                       project_id: str,
                       project_name: str,
                       workflow_type: str = 'standard',
                       session_type: str = 'project') -> Dict[str, Any]:
        """Create a new session"""
        session_id = str(uuid.uuid4())
        session = {
            'id': session_id,
            'project_id': project_id,
            'project_name': project_name,
            'status': 'idle',  # idle, running, completed, error
            'created_at': datetime.now().isoformat(),
            'workflow_progress': None,
            'file_progress': None,
            'current_step': None,
            'workflow_type': workflow_type,  # 'standard' or 'simple'
            'session_type': session_type  # 'project' or 'chat'
        }

        with self._lock:
            self._sessions[session_id] = session
            self._messages[session_id] = []

        return session

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID"""
        return self._sessions.get(session_id)

    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update session data"""
        if session_id not in self._sessions:
            return False

        with self._lock:
            self._sessions[session_id].update(updates)
        return True

    def delete_session(self, session_id: str) -> bool:
        """Delete a session"""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                if session_id in self._messages:
                    del self._messages[session_id]
                return True
        return False

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions"""
        return list(self._sessions.values())

    def add_message(self,
                    session_id: str,
                    role: str,
                    content: str,
                    message_type: str = 'text',
                    metadata: Dict[str, Any] = None) -> bool:
        """Add a message to a session"""
        if session_id not in self._sessions:
            return False

        message = {
            'id': str(uuid.uuid4()),
            'role': role,  # user, assistant, system, tool
            'content': content,
            'type': message_type,  # text, tool_call, tool_result, error, log
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }

        with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = []
            self._messages[session_id].append(message)

        return True

    def get_messages(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get all messages for a session"""
        if session_id not in self._sessions:
            return None
        return self._messages.get(session_id, [])

    def update_last_message(self, session_id: str, content: str) -> bool:
        """Update the content of the last message (for streaming)"""
        if session_id not in self._messages or not self._messages[session_id]:
            return False

        with self._lock:
            self._messages[session_id][-1]['content'] = content
        return True

    def set_workflow_progress(self, session_id: str,
                              progress: Dict[str, Any]) -> bool:
        """Set workflow progress for a session"""
        if session_id not in self._sessions:
            return False

        with self._lock:
            self._sessions[session_id]['workflow_progress'] = progress
        return True

    def set_file_progress(self, session_id: str, progress: Dict[str,
                                                                Any]) -> bool:
        """Set file writing progress for a session"""
        if session_id not in self._sessions:
            return False

        with self._lock:
            self._sessions[session_id]['file_progress'] = progress
        return True

    def set_current_step(self, session_id: str, step: str) -> bool:
        """Set the current workflow step"""
        if session_id not in self._sessions:
            return False

        with self._lock:
            self._sessions[session_id]['current_step'] = step
        return True
