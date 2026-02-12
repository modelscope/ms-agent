# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Session management API endpoints
Handles session lifecycle, message history, and session state
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from .models import SessionCreate, SessionInfo, MessageCreate, APIResponse, PaginatedResponse
from .session_manager import SessionManager

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])

# Initialize global session manager
session_manager = SessionManager()


# ============================================================
# API Endpoints
# ============================================================

@router.post("")
async def create_session(request: SessionCreate):
    """Create a new session"""
    try:
        # Default values for chat mode
        project_id = request.project_id or 'chat'
        project_name = 'Chat Session' if not request.project_id else request.project_id
        
        session = session_manager.create_session(
            project_id=project_id,
            project_name=project_name,
            workflow_type=request.workflow_type,
            session_type=request.session_type
        )
        
        return APIResponse(
            success=True,
            message="Session created successfully",
            data=session
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all sessions with pagination"""
    try:
        sessions = session_manager.list_sessions()
        
        # Sort by created_at (most recent first)
        sessions.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Apply pagination
        total = len(sessions)
        paginated_sessions = sessions[offset:offset + limit]
        
        return PaginatedResponse(
            success=True,
            data=paginated_sessions,
            pagination={
                'limit': limit,
                'offset': offset,
                'total': total
            },
            total=total
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get session details by ID"""
    try:
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(success=True, data=session)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{session_id}")
async def update_session(session_id: str, updates: dict):
    """Update session data"""
    try:
        success = session_manager.update_session(session_id, updates)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(
            success=True,
            message="Session updated successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    try:
        success = session_manager.delete_session(session_id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(
            success=True,
            message="Session deleted successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get all messages for a session"""
    try:
        messages = session_manager.get_messages(session_id)
        if messages is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(success=True, data=messages)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/messages")
async def add_message(session_id: str, message: MessageCreate):
    """Add a message to a session"""
    try:
        success = session_manager.add_message(
            session_id=session_id,
            role=message.role,
            content=message.content,
            message_type=message.type,
            metadata=message.metadata
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(
            success=True,
            message="Message added successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/events")
async def get_dr_events(
    session_id: str,
    after_id: Optional[int] = Query(None)
):
    """Get deep research events for a session"""
    try:
        events = session_manager.list_dr_events(session_id, after_id=after_id)
        if events is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(success=True, data=events)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/progress")
async def get_progress_events(
    session_id: str,
    after_timestamp: Optional[str] = Query(None)
):
    """Get progress events for a session"""
    try:
        events = session_manager.get_progress_events(session_id, after_timestamp=after_timestamp)
        if events is None:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return APIResponse(success=True, data=events)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
