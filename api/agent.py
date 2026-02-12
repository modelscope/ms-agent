# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Agent execution API endpoints
Handles agent execution, workflow running, and task management
"""
import asyncio
import os
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from threading import Thread

from .models import AgentRunRequest, AgentStopRequest, APIResponse
from .session import session_manager
from .config import config_manager
from .project import project_discovery
from .websocket import manager as ws_manager
from .agent_executor import AgentExecutor

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

# Store running agent executors
running_agents: Dict[str, AgentExecutor] = {}


# ============================================================
# API Endpoints
# ============================================================

@router.post("/run")
async def run_agent(request: AgentRunRequest):
    """Start agent execution for a session"""
    try:
        # Check if session exists
        session = session_manager.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Check if agent is already running for this session
        if request.session_id in running_agents:
            raise HTTPException(status_code=400, detail="Agent already running for this session")
        
        # Update session status
        session_manager.update_session(request.session_id, {'status': 'running'})
        
        # Add user message to session
        session_manager.add_message(
            session_id=request.session_id,
            role='user',
            content=request.query,
            message_type='text'
        )
        
        # Get configuration
        llm_config = config_manager.get_llm_config()
        
        # Get project information
        project_id = request.project_id or 'chat'
        if project_id == 'chat':
            # For simple chat, use default agent config
            from ms_agent.config import Config
            import os
            agent_config_path = os.path.join(
                os.path.dirname(__file__), '..', 'ms_agent', 'agent', 'agent.yaml'
            )
            project = {
                'config_file': agent_config_path,
                'type': 'agent'
            }
        else:
            project = project_discovery.get_project(project_id)
            if not project:
                raise HTTPException(status_code=404, detail="Project not found")
        
        # Create agent executor
        executor = AgentExecutor(
            session_id=request.session_id,
            config_file=project['config_file'],
            llm_config=llm_config,
            query=request.query,
            session_manager=session_manager,
            ws_manager=ws_manager,
            workflow_type=request.workflow_type,
            project_type=project.get('type', 'agent')
        )
        
        # Store executor
        running_agents[request.session_id] = executor
        
        # Start execution in background
        asyncio.create_task(executor.execute())
        
        return APIResponse(
            success=True,
            message="Agent execution started",
            data={'session_id': request.session_id, 'project_id': project_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        # Update session status to error
        session_manager.update_session(request.session_id, {'status': 'error'})
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_agent(request: AgentStopRequest):
    """Stop agent execution for a session"""
    try:
        # Check if agent is running
        if request.session_id not in running_agents:
            raise HTTPException(status_code=400, detail="No running agent for this session")
        
        # Get executor and cancel
        executor = running_agents[request.session_id]
        executor.cancel()
        
        # Clean up running agent
        del running_agents[request.session_id]
        
        # Update session status
        session_manager.update_session(request.session_id, {'status': 'stopped'})
        
        # Broadcast stop status via WebSocket
        await ws_manager.broadcast_to_session({
            'type': 'status',
            'status': 'stopped',
            'message': 'Agent execution stopped by user',
            'timestamp': asyncio.get_event_loop().time()
        }, request.session_id)
        
        return APIResponse(
            success=True,
            message="Agent execution stopped",
            data={'session_id': request.session_id}
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{session_id}")
async def get_agent_status(session_id: str):
    """Get agent execution status for a session"""
    try:
        session = session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        is_running = session_id in running_agents
        
        return APIResponse(
            success=True,
            data={
                'session_id': session_id,
                'status': session.get('status', 'idle'),
                'is_running': is_running,
                'current_step': session.get('current_step'),
                'workflow_progress': session.get('workflow_progress'),
                'file_progress': session.get('file_progress')
            }
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
