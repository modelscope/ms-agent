# Copyright (c) Alibaba, Inc. and its affiliates.
"""
WebSocket handler for real-time communication
Handles agent execution, log streaming, and progress updates.
"""
import asyncio
import os
from datetime import datetime
from typing import Any, Dict, Set

import json
from agent_runner import AgentRunner
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
# Import shared instances
from shared import config_manager, project_discovery, session_manager

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections"""

    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.log_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket, session_id: str):
        """Connect a client to a session"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)

    async def connect_logs(self, websocket: WebSocket):
        """Connect a client to log stream"""
        await websocket.accept()
        self.log_connections.add(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str = None):
        """Disconnect a client"""
        if session_id and session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        self.log_connections.discard(websocket)

    async def send_to_session(self, session_id: str, message: Dict[str, Any]):
        """Send message to all clients in a session"""
        if session_id in self.active_connections:
            disconnected = set()
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    disconnected.add(connection)
            for conn in disconnected:
                self.active_connections[session_id].discard(conn)

    async def broadcast_log(self, log_entry: Dict[str, Any]):
        """Broadcast log entry to all log connections"""
        disconnected = set()
        for connection in self.log_connections:
            try:
                await connection.send_json(log_entry)
            except Exception:
                disconnected.add(connection)
        for conn in disconnected:
            self.log_connections.discard(conn)


connection_manager = ConnectionManager()
agent_runners: Dict[str, AgentRunner] = {}
agent_tasks: Dict[str, asyncio.Task] = {}


@router.websocket('/session/{session_id}')
async def websocket_session(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for session communication"""
    print(f'[WS] Client connecting to session: {session_id}')
    await connection_manager.connect(websocket, session_id)
    print(f'[WS] Client connected to session: {session_id}')

    try:
        while True:
            data = await websocket.receive_json()
            print(f'[WS] Received message: {data}')
            await handle_session_message(session_id, data, websocket)
    except WebSocketDisconnect:
        print(f'[WS] Client disconnected from session: {session_id}')
        connection_manager.disconnect(websocket, session_id)
        # Stop agent if running
        if session_id in agent_runners:
            await agent_runners[session_id].stop()
            del agent_runners[session_id]
        if session_id in agent_tasks:
            agent_tasks[session_id].cancel()
            del agent_tasks[session_id]


@router.websocket('/logs')
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for log streaming"""
    await connection_manager.connect_logs(websocket)

    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)


async def handle_session_message(session_id: str, data: Dict[str, Any],
                                 websocket: WebSocket):
    """Handle incoming WebSocket messages"""
    action = data.get('action')

    if action == 'start':
        await start_agent(session_id, data, websocket)
    elif action == 'stop':
        await stop_agent(session_id)
    elif action == 'send_input':
        await send_input(session_id, data)
    elif action == 'get_status':
        await send_status(session_id, websocket)


async def start_agent(session_id: str, data: Dict[str, Any],
                      websocket: WebSocket):
    """Start an agent for a session"""
    print(f'[Agent] Starting agent for session: {session_id}')

    session = session_manager.get_session(session_id)
    if not session:
        print(f'[Agent] ERROR: Session not found: {session_id}')
        await websocket.send_json({
            'type': 'error',
            'message': 'Session not found'
        })
        return

    project = project_discovery.get_project(session['project_id'])
    if not project:
        print(f"[Agent] ERROR: Project not found: {session['project_id']}")
        await websocket.send_json({
            'type': 'error',
            'message': 'Project not found'
        })
        return

    # Clean up output directory for code_genesis before starting
    if project['id'] == 'code_genesis':
        output_dir = os.path.join(project['path'], 'output')
        if os.path.exists(output_dir):
            try:
                import shutil
                shutil.rmtree(output_dir)
                print(f'[Agent] Cleaned up output directory: {output_dir}')
                await connection_manager.send_to_session(
                    session_id, {
                        'type': 'log',
                        'level': 'info',
                        'message': 'Cleaned up previous output directory',
                        'timestamp': datetime.now().isoformat()
                    })
            except Exception as e:
                print(
                    f'[Agent] WARNING: Failed to clean output directory: {e}')
                # Don't fail if cleanup fails, just log it

    # Get workflow_type from session (default to 'standard')
    workflow_type = session.get('workflow_type', 'standard')

    print(f"[Agent] Project: {project['id']}, type: {project['type']}, "
          f"config: {project['config_file']}, workflow_type: {workflow_type}")

    query = data.get('query', '')
    print(f'[Agent] Query: {query[:100]}...'
          if len(query) > 100 else f'[Agent] Query: {query}')

    # Add user message to session (but don't broadcast - frontend already has it)
    session_manager.add_message(session_id, 'user', query, 'text')

    # Create agent runner with workflow_type
    runner = AgentRunner(
        session_id=session_id,
        project=project,
        config_manager=config_manager,
        on_output=lambda msg: asyncio.create_task(
            on_agent_output(session_id, msg)),
        on_log=lambda log: asyncio.create_task(on_agent_log(session_id, log)),
        on_progress=lambda prog: asyncio.create_task(
            on_agent_progress(session_id, prog)),
        on_complete=lambda result: asyncio.create_task(
            on_agent_complete(session_id, result)),
        on_error=lambda err: asyncio.create_task(
            on_agent_error(session_id, err)),
        workflow_type=workflow_type)

    agent_runners[session_id] = runner
    session_manager.update_session(session_id, {'status': 'running'})

    # Notify session started
    await connection_manager.send_to_session(session_id, {
        'type': 'status',
        'status': 'running'
    })

    # Start agent in background so the WS loop can still receive stop/input messages
    task = asyncio.create_task(runner.start(query))
    agent_tasks[session_id] = task

    def _cleanup(_task: asyncio.Task):
        agent_tasks.pop(session_id, None)

    task.add_done_callback(_cleanup)


async def stop_agent(session_id: str):
    """Stop a running agent"""
    if session_id in agent_runners:
        await agent_runners[session_id].stop()
        del agent_runners[session_id]
    if session_id in agent_tasks:
        agent_tasks[session_id].cancel()
        del agent_tasks[session_id]

    session_manager.update_session(session_id, {'status': 'stopped'})
    await connection_manager.send_to_session(session_id, {
        'type': 'status',
        'status': 'stopped'
    })


async def send_input(session_id: str, data: Dict[str, Any]):
    """Send input to a running agent"""
    if session_id not in agent_runners:
        print(f'[WS] ERROR: Agent runner not found for session: {session_id}')
        await connection_manager.send_to_session(
            session_id, {
                'type':
                'error',
                'message':
                ('Agent is not running. The workflow may have completed. '
                 'Please start a new conversation or restart the agent.')
            })
        return

    input_text = data.get('input', '')
    print(f'[WS] Sending input to agent: {input_text[:100]}...')

    # Check if process is still alive
    runner = agent_runners[session_id]
    if runner.process and runner.process.returncode is not None:
        print(
            f'[WS] ERROR: Process has exited with code {runner.process.returncode}'
        )
        await connection_manager.send_to_session(
            session_id, {
                'type':
                'error',
                'message':
                'Agent process has terminated. The workflow completed. Please start a new conversation to continue.'
            })
        # Clean up the runner
        del agent_runners[session_id]
        return

    # Update session status to running
    session_manager.update_session(session_id, {'status': 'running'})
    await connection_manager.send_to_session(session_id, {
        'type': 'status',
        'status': 'running'
    })

    # Add user message to session
    session_manager.add_message(session_id, 'user', input_text, 'text')

    # Send input to agent
    try:
        await runner.send_input(input_text)
    except Exception as e:
        print(f'[WS] ERROR: Failed to send input: {e}')
        await connection_manager.send_to_session(
            session_id, {
                'type':
                'error',
                'message':
                f'Failed to send input: {str(e)}. The process may have terminated.'
            })


async def send_status(session_id: str, websocket: WebSocket):
    """Send current status to a client"""
    session = session_manager.get_session(session_id)
    if session:
        await websocket.send_json({
            'type':
            'status',
            'session':
            session,
            'messages':
            session_manager.get_messages(session_id)
        })


async def on_agent_output(session_id: str, message: Dict[str, Any]):
    """Handle agent output"""
    msg_type = message.get('type', 'text')
    content = message.get('content', '')
    role = message.get('role', 'assistant')

    if msg_type == 'stream':
        # Streaming update
        await connection_manager.send_to_session(
            session_id, {
                'type': 'stream',
                'content': content,
                'done': message.get('done', False)
            })
        if message.get('done'):
            session_manager.add_message(session_id, role, content, 'text')
    else:
        session_manager.add_message(session_id, role, content, msg_type,
                                    message.get('metadata'))
        await connection_manager.send_to_session(
            session_id, {
                'type': 'message',
                'role': role,
                'content': content,
                'message_type': msg_type,
                'metadata': message.get('metadata')
            })


async def on_agent_log(session_id: str, log: Dict[str, Any]):
    """Handle agent log"""
    await connection_manager.send_to_session(session_id, {
        'type': 'log',
        **log
    })
    await connection_manager.broadcast_log({'session_id': session_id, **log})


async def on_agent_progress(session_id: str, progress: Dict[str, Any]):
    """Handle progress update"""
    progress_type = progress.get('type', 'workflow')

    if progress_type == 'workflow':
        session_manager.set_workflow_progress(session_id, progress)
        session_manager.set_current_step(session_id,
                                         progress.get('current_step'))
    elif progress_type == 'file':
        session_manager.set_file_progress(session_id, progress)

    await connection_manager.send_to_session(session_id, {
        'type': 'progress',
        **progress
    })


async def on_agent_complete(session_id: str, result: Dict[str, Any]):
    """Handle agent completion"""
    session_manager.update_session(session_id, {'status': 'completed'})

    if session_id in agent_runners:
        del agent_runners[session_id]
    if session_id in agent_tasks:
        agent_tasks[session_id].cancel()
        del agent_tasks[session_id]

    await connection_manager.send_to_session(session_id, {
        'type': 'complete',
        'result': result
    })


async def on_agent_error(session_id: str, error: Dict[str, Any]):
    """Handle agent error"""
    session_manager.update_session(session_id, {'status': 'error'})
    session_manager.add_message(session_id, 'system',
                                error.get('message', 'Unknown error'), 'error')

    if session_id in agent_runners:
        del agent_runners[session_id]
    if session_id in agent_tasks:
        agent_tasks[session_id].cancel()
        del agent_tasks[session_id]

    await connection_manager.send_to_session(session_id, {
        'type': 'error',
        **error
    })
