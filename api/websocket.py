# Copyright (c) Alibaba, Inc. and its affiliates.
"""
WebSocket communication API
Provides real-time bidirectional communication for agent execution
"""
import json
import asyncio
from typing import Dict, List
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .session import session_manager
from .config import config_manager
from .agent_executor import AgentExecutor

router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Connect a websocket for a session"""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, session_id: str):
        """Disconnect a websocket"""
        if session_id in self.active_connections:
            if websocket in self.active_connections[session_id]:
                self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send a message to a specific websocket"""
        await websocket.send_json(message)
    
    async def broadcast_to_session(self, message: dict, session_id: str):
        """Broadcast a message to all connections of a session"""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass


# Initialize connection manager
manager = ConnectionManager()

# Store running agent executors for WebSocket connections
running_agents: Dict[str, AgentExecutor] = {}


# ============================================================
# WebSocket Endpoints
# ============================================================

@router.websocket("/agent/{session_id}")
async def websocket_agent(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time agent communication
    
    Message types:
    - status: Agent status updates
    - log: Log messages
    - error: Error messages
    - progress: Progress updates
    - result: Final results
    - stream: Streaming output
    """
    await manager.connect(websocket, session_id)
    
    try:
        # Send connection confirmation
        await manager.send_personal_message({
            'type': 'connected',
            'session_id': session_id,
            'timestamp': datetime.now().isoformat()
        }, websocket)
        
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            message_type = message.get('type')
            
            if message_type == 'ping':
                # Respond to ping
                await manager.send_personal_message({
                    'type': 'pong',
                    'timestamp': datetime.now().isoformat()
                }, websocket)
            
            elif message_type == 'start':
                # Start agent execution
                query = message.get('query', '')
                project_id = message.get('project_id', 'chat')
                
                # Check if already running
                if session_id in running_agents:
                    await manager.send_personal_message({
                        'type': 'error',
                        'error': 'Agent already running for this session',
                        'timestamp': datetime.now().isoformat()
                    }, websocket)
                    continue
                
                # Update session
                session_manager.update_session(session_id, {'status': 'running'})
                
                # Get LLM configuration
                llm_config = config_manager.get_llm_config()
                
                # Get project information
                if project_id == 'chat':
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
                    from .project import project_discovery
                    project = project_discovery.get_project(project_id)
                    if not project:
                        await manager.send_personal_message({
                            'type': 'error',
                            'error': 'Project not found',
                            'timestamp': datetime.now().isoformat()
                        }, websocket)
                        continue
                
                # Create agent executor
                executor = AgentExecutor(
                    session_id=session_id,
                    config_file=project['config_file'],
                    llm_config=llm_config,
                    query=query,
                    session_manager=session_manager,
                    ws_manager=manager,
                    workflow_type=message.get('workflow_type', 'standard'),
                    project_type=project.get('type', 'agent')
                )
                
                # Store executor
                running_agents[session_id] = executor
                
                # Start execution in background
                asyncio.create_task(executor.execute())
            
            elif message_type == 'stop':
                # Stop agent execution
                if session_id in running_agents:
                    executor = running_agents[session_id]
                    executor.cancel()
                    del running_agents[session_id]
                
                session_manager.update_session(session_id, {'status': 'stopped'})
                
                await manager.broadcast_to_session({
                    'type': 'status',
                    'status': 'stopped',
                    'message': 'Agent execution stopped',
                    'timestamp': datetime.now().isoformat()
                }, session_id)
    
    except WebSocketDisconnect:
        manager.disconnect(websocket, session_id)
    except Exception as e:
        # Send error message
        try:
            await manager.send_personal_message({
                'type': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }, websocket)
        except Exception:
            pass
        manager.disconnect(websocket, session_id)


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for chat functionality
    Similar to Sirchmunk's chat WebSocket
    """
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            request_data = json.loads(data)
            
            message = request_data.get('message', '')
            session_id = request_data.get('session_id')
            
            if not session_id:
                # Create new session for chat
                session = session_manager.create_session(
                    project_id='chat',
                    project_name='Chat Session',
                    session_type='chat'
                )
                session_id = session['id']
                
                # Send session ID to client
                await websocket.send_json({
                    'type': 'session',
                    'session_id': session_id
                })
            
            # Add user message to session
            session_manager.add_message(
                session_id=session_id,
                role='user',
                content=message,
                message_type='text'
            )
            
            # Get LLM configuration
            llm_config = config_manager.get_llm_config()
            
            # Create simple agent for chat
            from ms_agent.agent import LLMAgent
            from ms_agent.config import Config
            from omegaconf import DictConfig
            import os
            
            # Build config
            agent_config_path = os.path.join(
                os.path.dirname(__file__), '..', 'ms_agent', 'agent', 'agent.yaml'
            )
            config = Config.from_task(agent_config_path)
            
            # Override LLM config
            if llm_config.api_key:
                config.llm.api_key = llm_config.api_key
            if llm_config.model:
                config.llm.model = llm_config.model
            if llm_config.base_url:
                config.llm.base_url = llm_config.base_url
            
            # Create agent
            agent = LLMAgent(config=config, tag='chat')
            
            # Stream response
            try:
                async for messages in agent.run(message, stream=True):
                    if messages and len(messages) > 0:
                        content = messages[-1].content
                        await websocket.send_json({
                            'type': 'stream',
                            'content': content,
                            'session_id': session_id
                        })
                
                # Send final result
                final_content = messages[-1].content if messages else ''
                await websocket.send_json({
                    'type': 'result',
                    'content': final_content,
                    'session_id': session_id
                })
                
                # Add assistant message to session
                session_manager.add_message(
                    session_id=session_id,
                    role='assistant',
                    content=final_content,
                    message_type='text'
                )
            except Exception as e:
                await websocket.send_json({
                    'type': 'error',
                    'error': str(e)
                })
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                'type': 'error',
                'error': str(e)
            })
        except Exception:
            pass
