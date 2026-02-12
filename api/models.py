# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Data models for API requests and responses
"""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ============================================================
# Session Models
# ============================================================

class SessionCreate(BaseModel):
    """Request model for creating a new session"""
    project_id: Optional[str] = None
    query: Optional[str] = None
    workflow_type: Optional[str] = 'standard'
    session_type: Optional[str] = 'project'  # 'project' or 'chat'


class SessionInfo(BaseModel):
    """Session information model"""
    id: str
    project_id: str
    project_name: str
    status: str  # idle, running, completed, error
    created_at: str
    session_type: Optional[str] = 'project'
    workflow_progress: Optional[Dict[str, Any]] = None
    file_progress: Optional[Dict[str, Any]] = None
    current_step: Optional[str] = None


class MessageCreate(BaseModel):
    """Request model for creating a message"""
    role: str  # user, assistant, system, tool
    content: str
    type: str = 'text'  # text, tool_call, tool_result, error, log
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# Configuration Models
# ============================================================

class LLMConfig(BaseModel):
    """LLM configuration model"""
    provider: str = 'openai'
    model: str = 'qwen-plus'
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: Optional[float] = None
    temperature_enabled: Optional[bool] = False
    max_tokens: Optional[int] = None


class EditFileConfig(BaseModel):
    """Edit file configuration model"""
    api_key: Optional[str] = None
    base_url: str = 'https://api.morphllm.com/v1'
    diff_model: str = 'morph-v3-fast'


class SearchKeysConfig(BaseModel):
    """Search API keys configuration"""
    exa_api_key: Optional[str] = None
    serpapi_api_key: Optional[str] = None


class DeepResearchAgentConfig(BaseModel):
    """Deep research agent configuration"""
    model: Optional[str] = ''
    api_key: Optional[str] = ''
    base_url: Optional[str] = ''


class DeepResearchSearchConfig(BaseModel):
    """Deep research search configuration"""
    summarizer_model: Optional[str] = ''
    summarizer_api_key: Optional[str] = ''
    summarizer_base_url: Optional[str] = ''


class DeepResearchConfig(BaseModel):
    """Complete deep research configuration"""
    researcher: DeepResearchAgentConfig = Field(default_factory=DeepResearchAgentConfig)
    searcher: DeepResearchAgentConfig = Field(default_factory=DeepResearchAgentConfig)
    reporter: DeepResearchAgentConfig = Field(default_factory=DeepResearchAgentConfig)
    search: DeepResearchSearchConfig = Field(default_factory=DeepResearchSearchConfig)


class MCPServerConfig(BaseModel):
    """MCP server configuration"""
    name: str
    type: str  # 'stdio' or 'sse'
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None


class EdgeOnePagesConfig(BaseModel):
    """EdgeOne Pages configuration"""
    api_token: Optional[str] = None
    project_name: Optional[str] = None


# ============================================================
# Project Models
# ============================================================

class ProjectInfo(BaseModel):
    """Project information model"""
    id: str
    name: str
    display_name: str
    description: str
    type: str  # 'workflow' or 'agent'
    path: str
    has_readme: bool
    supports_workflow_switch: bool = False


# ============================================================
# Agent Execution Models
# ============================================================

class AgentRunRequest(BaseModel):
    """Request model for running an agent"""
    session_id: str
    query: str
    project_id: Optional[str] = None
    workflow_type: Optional[str] = 'standard'
    config: Optional[Dict[str, Any]] = None


class AgentStopRequest(BaseModel):
    """Request model for stopping an agent"""
    session_id: str


# ============================================================
# Chat Models
# ============================================================

class ChatMessage(BaseModel):
    """Chat message model"""
    role: str
    content: str
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    """Request model for chat endpoint"""
    session_id: Optional[str] = None
    message: str
    history: Optional[List[ChatMessage]] = []
    enable_rag: Optional[bool] = False
    enable_web_search: Optional[bool] = False
    kb_name: Optional[str] = None


# ============================================================
# Response Models
# ============================================================

class APIResponse(BaseModel):
    """Standard API response model"""
    success: bool
    message: Optional[str] = None
    data: Optional[Any] = None
    error: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Paginated response model"""
    success: bool
    data: List[Any]
    pagination: Dict[str, Any]
    total: int


# ============================================================
# WebSocket Message Models
# ============================================================

class WSMessage(BaseModel):
    """WebSocket message model"""
    type: str  # status, log, error, result, stream, etc.
    content: Optional[Any] = None
    timestamp: Optional[str] = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None


class WSErrorMessage(WSMessage):
    """WebSocket error message"""
    type: str = "error"
    error_code: Optional[str] = None


class WSLogMessage(WSMessage):
    """WebSocket log message"""
    type: str = "log"
    level: str = "info"  # debug, info, warning, error


class WSProgressMessage(WSMessage):
    """WebSocket progress message"""
    type: str = "progress"
    progress: float  # 0.0 to 1.0
    stage: Optional[str] = None
