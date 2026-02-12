# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Agent Execution Engine
Handles LLMAgent and Workflow execution with WebSocket callback integration
"""
import asyncio
import os
import traceback
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from omegaconf import DictConfig, OmegaConf

from ms_agent.agent import LLMAgent
from ms_agent.callbacks import Callback
from ms_agent.agent.runtime import Runtime
from ms_agent.llm.utils import Message
from ms_agent.config import Config
from ms_agent.workflow.dag_workflow import DAGWorkflow
from ms_agent.workflow.chain_workflow import ChainWorkflow

from .utils import get_session_work_dir, format_error_message

# Configure logger
logger = logging.getLogger(__name__)


class WebSocketCallback(Callback):
    """
    Custom callback that broadcasts agent events to WebSocket clients
    """
    
    def __init__(self, config: DictConfig, session_id: str, session_manager, ws_manager):
        super().__init__(config)
        self.session_id = session_id
        self.session_manager = session_manager
        self.ws_manager = ws_manager
    
    async def on_task_begin(self, runtime: Runtime, messages: list[Message]) -> None:
        """Called when a task begins"""
        await self._broadcast({
            'type': 'status',
            'status': 'running',
            'message': 'Task started',
            'round': runtime.round,
            'timestamp': datetime.now().isoformat()
        })
        
        # Add progress event
        self.session_manager.add_progress_event(
            self.session_id,
            {'event': 'task_begin', 'round': runtime.round}
        )
    
    async def on_generate_response(self, runtime: Runtime, messages: list[Message]):
        """Called before LLM generates response"""
        await self._broadcast({
            'type': 'log',
            'level': 'info',
            'message': f'Generating response (round {runtime.round})',
            'timestamp': datetime.now().isoformat()
        })
    
    async def on_tool_call(self, runtime: Runtime, messages: list[Message]):
        """Called after LLM generates response with tool calls"""
        last_message = messages[-1]
        
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                await self._broadcast({
                    'type': 'tool_call',
                    'tool_name': tool_call.get('tool_name'),
                    'tool_args': tool_call.get('arguments'),
                    'tool_call_id': tool_call.get('id'),
                    'timestamp': datetime.now().isoformat()
                })
                
                # Add to session messages
                self.session_manager.add_message(
                    session_id=self.session_id,
                    role='assistant',
                    content=f"Calling tool: {tool_call.get('tool_name')}",
                    message_type='tool_call',
                    metadata={'tool_call': tool_call}
                )
    
    async def after_tool_call(self, runtime: Runtime, messages: list[Message]):
        """Called after calling tools"""
        # Find tool result messages
        for msg in reversed(messages):
            if msg.role == 'tool':
                await self._broadcast({
                    'type': 'tool_result',
                    'tool_name': msg.name,
                    'tool_call_id': msg.tool_call_id,
                    'result': msg.content[:500] if len(msg.content) > 500 else msg.content,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Add to session messages
                self.session_manager.add_message(
                    session_id=self.session_id,
                    role='tool',
                    content=msg.content,
                    message_type='tool_result',
                    metadata={'tool_call_id': msg.tool_call_id, 'name': msg.name}
                )
                break
    
    async def on_task_end(self, runtime: Runtime, messages: list[Message]):
        """Called when a task finishes"""
        # Get final result
        final_content = messages[-1].content if messages else ''
        
        await self._broadcast({
            'type': 'result',
            'content': final_content,
            'round': runtime.round,
            'timestamp': datetime.now().isoformat()
        })
        
        # Add final message to session
        self.session_manager.add_message(
            session_id=self.session_id,
            role='assistant',
            content=final_content,
            message_type='text'
        )
        
        # Add progress event
        self.session_manager.add_progress_event(
            self.session_id,
            {'event': 'task_end', 'round': runtime.round}
        )
    
    async def _broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all WebSocket connections for this session"""
        try:
            await self.ws_manager.broadcast_to_session(message, self.session_id)
        except Exception as e:
            # Don't fail the agent execution if broadcast fails
            print(f"Warning: Failed to broadcast message: {e}")


class AgentExecutor:
    """
    Agent execution engine that manages LLMAgent and Workflow lifecycle
    """
    
    def __init__(
        self,
        session_id: str,
        config_file: str,
        llm_config: Any,
        query: str,
        session_manager,
        ws_manager,
        workflow_type: str = 'standard',
        project_type: str = 'agent'
    ):
        self.session_id = session_id
        self.config_file = config_file
        self.llm_config = llm_config
        self.query = query
        self.session_manager = session_manager
        self.ws_manager = ws_manager
        self.workflow_type = workflow_type
        self.project_type = project_type
        
        self.should_stop = False
        self.agent = None
        self.workflow = None
    
    def build_config(self) -> DictConfig:
        """Build agent configuration by merging project config and LLM config"""
        # Load project configuration
        project_config = Config.from_task(self.config_file)
        
        # Override LLM configuration
        if self.llm_config.api_key:
            if not hasattr(project_config, 'llm'):
                project_config.llm = DictConfig({})
            project_config.llm.api_key = self.llm_config.api_key
        
        if self.llm_config.model:
            project_config.llm.model = self.llm_config.model
        
        if self.llm_config.base_url:
            project_config.llm.base_url = self.llm_config.base_url
        
        if self.llm_config.temperature is not None and self.llm_config.temperature_enabled:
            project_config.llm.temperature = self.llm_config.temperature
        
        if self.llm_config.max_tokens:
            project_config.llm.max_tokens = self.llm_config.max_tokens
        
        # Set output directory to session work dir
        work_dir = get_session_work_dir(self.session_id)
        project_config.output_dir = str(work_dir)
        
        # Add callback
        if not hasattr(project_config, 'callbacks'):
            project_config.callbacks = []
        
        # Store callback config for later instantiation
        self.callback_config = project_config
        
        return project_config
    
    async def execute(self):
        """Execute the agent or workflow"""
        logger.info(f"Starting execution for session {self.session_id}")
        try:
            # Update session status
            self.session_manager.update_session(self.session_id, {'status': 'running'})
            
            # Broadcast start status
            await self.ws_manager.broadcast_to_session({
                'type': 'status',
                'status': 'running',
                'message': 'Execution started',
                'timestamp': datetime.now().isoformat()
            }, self.session_id)
            
            # Build configuration
            config = self.build_config()
            logger.info(f"Built configuration for {self.project_type} execution")
            
            # Execute based on project type
            if self.project_type == 'workflow':
                await self._execute_workflow(config)
            else:
                await self._execute_agent(config)
            
            # Update session status to completed
            self.session_manager.update_session(self.session_id, {'status': 'completed'})
            logger.info(f"Execution completed for session {self.session_id}")
            
            # Broadcast completion
            await self.ws_manager.broadcast_to_session({
                'type': 'status',
                'status': 'completed',
                'message': 'Execution completed successfully',
                'timestamp': datetime.now().isoformat()
            }, self.session_id)
        
        except Exception as e:
            # Update session status to error
            self.session_manager.update_session(self.session_id, {'status': 'error'})
            
            error_msg = format_error_message(e)
            error_trace = traceback.format_exc()
            
            logger.error(f"Execution error for session {self.session_id}: {error_msg}")
            logger.debug(f"Error traceback: {error_trace}")
            
            # Broadcast error
            await self.ws_manager.broadcast_to_session({
                'type': 'error',
                'error': error_msg,
                'details': error_trace,
                'timestamp': datetime.now().isoformat()
            }, self.session_id)
            
            # Add error message to session
            self.session_manager.add_message(
                session_id=self.session_id,
                role='system',
                content=f"Error: {error_msg}",
                message_type='error'
            )
    
    async def _execute_agent(self, config: DictConfig):
        """Execute a single LLMAgent"""
        # Create WebSocket callback
        ws_callback = WebSocketCallback(
            config=config,
            session_id=self.session_id,
            session_manager=self.session_manager,
            ws_manager=self.ws_manager
        )
        
        # Add callback to config
        config.callbacks = [ws_callback]
        
        # Create agent
        self.agent = LLMAgent(
            config=config,
            tag=self.session_id,
            trust_remote_code=False
        )
        
        # Run agent
        async for messages in self.agent.run(self.query, stream=False):
            if self.should_stop:
                break
            
            # Messages are already handled by callbacks
            pass
    
    async def _execute_workflow(self, config: DictConfig):
        """Execute a DAG or Chain workflow"""
        # Determine workflow file
        config_dir = os.path.dirname(self.config_file)
        
        if self.workflow_type == 'simple':
            workflow_file = os.path.join(config_dir, 'simple_workflow.yaml')
            if not os.path.exists(workflow_file):
                workflow_file = self.config_file
        else:
            workflow_file = self.config_file
        
        # Load workflow configuration
        workflow_config = Config.from_task(workflow_file)
        
        # Override LLM config (similar to agent)
        if self.llm_config.api_key:
            if not hasattr(workflow_config, 'llm'):
                workflow_config.llm = DictConfig({})
            workflow_config.llm.api_key = self.llm_config.api_key
        
        if self.llm_config.model:
            workflow_config.llm.model = self.llm_config.model
        
        # Set output directory
        work_dir = get_session_work_dir(self.session_id)
        workflow_config.output_dir = str(work_dir)
        
        # Determine workflow type
        workflow_structure = workflow_config.get('workflow', {})
        is_dag = 'nodes' in workflow_structure
        
        # Create workflow
        if is_dag:
            self.workflow = DAGWorkflow(
                config_dir_or_id=workflow_file,
                config=workflow_config,
                trust_remote_code=False
            )
        else:
            self.workflow = ChainWorkflow(
                config_dir_or_id=workflow_file,
                config=workflow_config,
                trust_remote_code=False
            )
        
        # Broadcast workflow info
        await self.ws_manager.broadcast_to_session({
            'type': 'log',
            'level': 'info',
            'message': f'Starting {"DAG" if is_dag else "Chain"} workflow',
            'timestamp': datetime.now().isoformat()
        }, self.session_id)
        
        # Run workflow
        result = await self.workflow.run(self.query)
        
        # Broadcast workflow result
        await self.ws_manager.broadcast_to_session({
            'type': 'result',
            'content': str(result),
            'timestamp': datetime.now().isoformat()
        }, self.session_id)
    
    def cancel(self):
        """Cancel the execution"""
        self.should_stop = True
        
        # Try to stop agent
        if self.agent and hasattr(self.agent, 'runtime'):
            self.agent.runtime.should_stop = True
