# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Configuration management API endpoints
Handles LLM configuration, search keys, and other settings
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import (
    LLMConfig,
    EditFileConfig,
    SearchKeysConfig,
    DeepResearchAgentConfig,
    DeepResearchSearchConfig,
    APIResponse,
    MCPServerConfig,
    EdgeOnePagesConfig,
    DeepResearchConfig
)
from .utils import load_json_file, save_json_file, mask_sensitive_value

router = APIRouter(prefix="/api/v1/config", tags=["config"])


class ConfigManager:
    """Manages configuration persistence"""
    
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.expanduser("~/.ms-agent/config")
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "settings.json"
        self.mcp_file = self.config_dir / "mcp_servers.json"
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if self.config_file.exists():
            config = load_json_file(str(self.config_file))
            if not config:
                config = {}
        else:
            config = {}
        
        # Load MCP servers from separate file if exists
        if self.mcp_file.exists():
            try:
                mcp_data = load_json_file(str(self.mcp_file))
                if mcp_data:
                    if 'mcpServers' in mcp_data:
                        config['mcp_servers'] = mcp_data['mcpServers']
                    else:
                        config['mcp_servers'] = mcp_data
            except Exception:
                pass
        
        return config
    
    def _save_config(self) -> bool:
        """Save configuration to file"""
        # Save main config (without mcp_servers)
        config_to_save = {
            k: v for k, v in self._config.items() if k != 'mcp_servers'
        }
        success = save_json_file(str(self.config_file), config_to_save)
        
        # Save MCP servers to separate file (compatible with ms-agent format)
        mcp_data = {'mcpServers': self._config.get('mcp_servers', {})}
        mcp_success = save_json_file(str(self.mcp_file), mcp_data)
        
        return success and mcp_success
    
    def get_llm_config(self) -> LLMConfig:
        """Get LLM configuration"""
        llm_config = self._config.get('llm', {})
        return LLMConfig(**llm_config)
    
    def save_llm_config(self, config: LLMConfig) -> bool:
        """Save LLM configuration"""
        self._config['llm'] = config.dict()
        return self._save_config()
    
    def get_edit_file_config(self) -> EditFileConfig:
        """Get edit file configuration"""
        config = self._config.get('edit_file', {})
        return EditFileConfig(**config)
    
    def save_edit_file_config(self, config: EditFileConfig) -> bool:
        """Save edit file configuration"""
        self._config['edit_file'] = config.dict()
        return self._save_config()
    
    def get_search_keys(self) -> SearchKeysConfig:
        """Get search API keys"""
        config = self._config.get('search_keys', {})
        return SearchKeysConfig(**config)
    
    def save_search_keys(self, config: SearchKeysConfig) -> bool:
        """Save search API keys"""
        self._config['search_keys'] = config.dict()
        return self._save_config()
    
    def get_deep_research_agent_config(self) -> DeepResearchAgentConfig:
        """Get deep research agent configuration"""
        config = self._config.get('deep_research_agent', {})
        return DeepResearchAgentConfig(**config)
    
    def save_deep_research_agent_config(self, config: DeepResearchAgentConfig) -> bool:
        """Save deep research agent configuration"""
        self._config['deep_research_agent'] = config.dict()
        return self._save_config()
    
    def get_deep_research_search_config(self) -> DeepResearchSearchConfig:
        """Get deep research search configuration"""
        config = self._config.get('deep_research_search', {})
        return DeepResearchSearchConfig(**config)
    
    def save_deep_research_search_config(self, config: DeepResearchSearchConfig) -> bool:
        """Save deep research search configuration"""
        self._config['deep_research_search'] = config.dict()
        return self._save_config()
    
    def get_mcp_config(self) -> Dict[str, Any]:
        """Get MCP servers configuration"""
        return self._config.get('mcp_servers', {})
    
    def save_mcp_config(self, servers: Dict[str, Any]) -> bool:
        """Save MCP servers configuration"""
        self._config['mcp_servers'] = servers
        return self._save_config()
    
    def add_mcp_server(self, name: str, server_config: Dict[str, Any]) -> bool:
        """Add a new MCP server"""
        if 'mcp_servers' not in self._config:
            self._config['mcp_servers'] = {}
        self._config['mcp_servers'][name] = server_config
        return self._save_config()
    
    def remove_mcp_server(self, name: str) -> bool:
        """Remove an MCP server"""
        if name in self._config.get('mcp_servers', {}):
            del self._config['mcp_servers'][name]
            self._save_config()
            return True
        return False
    
    def get_edgeone_pages_config(self) -> Dict[str, Any]:
        """Get EdgeOne Pages configuration"""
        return self._config.get('edgeone_pages', {})
    
    def save_edgeone_pages_config(self, config: Dict[str, Any]) -> bool:
        """Save EdgeOne Pages configuration"""
        self._config['edgeone_pages'] = config
        return self._save_config()
    
    def get_deep_research_config(self) -> Dict[str, Any]:
        """Get complete deep research configuration"""
        return self._config.get('deep_research', {})
    
    def save_deep_research_config(self, config: Dict[str, Any]) -> bool:
        """Save complete deep research configuration"""
        self._config['deep_research'] = config
        return self._save_config()
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration"""
        return {
            'llm': self.get_llm_config().dict(),
            'edit_file': self.get_edit_file_config().dict(),
            'search_keys': self.get_search_keys().dict(),
            'deep_research': self.get_deep_research_config(),
            'mcp_servers': self.get_mcp_config(),
            'edgeone_pages': self.get_edgeone_pages_config()
        }
    
    def get_env_vars(self) -> Dict[str, str]:
        """Get environment variables for running agents"""
        env_vars = {}
        
        # LLM config
        llm = self.get_llm_config()
        if llm.api_key:
            provider = llm.provider or 'openai'
            if provider == 'modelscope':
                env_vars['MODELSCOPE_API_KEY'] = llm.api_key
            elif provider == 'openai':
                env_vars['OPENAI_API_KEY'] = llm.api_key
            elif provider == 'anthropic':
                env_vars['ANTHROPIC_API_KEY'] = llm.api_key
        
        if llm.base_url:
            env_vars['OPENAI_BASE_URL'] = llm.base_url
        
        # Search keys
        search_keys = self.get_search_keys()
        if search_keys.exa_api_key:
            env_vars['EXA_API_KEY'] = search_keys.exa_api_key
        if search_keys.serpapi_api_key:
            env_vars['SERPAPI_API_KEY'] = search_keys.serpapi_api_key
        
        return env_vars
    
    def get_mcp_file_path(self) -> str:
        """Get the path to the MCP servers file"""
        mcp_file = self.config_dir / 'mcp_servers.json'
        return str(mcp_file)


# Initialize global config manager
config_manager = ConfigManager()


# ============================================================
# API Endpoints
# ============================================================

@router.get("")
async def get_all_config():
    """Get all configuration settings"""
    try:
        config = config_manager.get_all_config()
        
        # Mask sensitive values
        if config.get('llm', {}).get('api_key'):
            config['llm']['api_key'] = mask_sensitive_value(config['llm']['api_key'])
        if config.get('edit_file', {}).get('api_key'):
            config['edit_file']['api_key'] = mask_sensitive_value(config['edit_file']['api_key'])
        if config.get('search_keys', {}).get('exa_api_key'):
            config['search_keys']['exa_api_key'] = mask_sensitive_value(config['search_keys']['exa_api_key'])
        if config.get('search_keys', {}).get('serpapi_api_key'):
            config['search_keys']['serpapi_api_key'] = mask_sensitive_value(config['search_keys']['serpapi_api_key'])
        if config.get('deep_research_agent', {}).get('api_key'):
            config['deep_research_agent']['api_key'] = mask_sensitive_value(config['deep_research_agent']['api_key'])
        if config.get('deep_research_search', {}).get('summarizer_api_key'):
            config['deep_research_search']['summarizer_api_key'] = mask_sensitive_value(
                config['deep_research_search']['summarizer_api_key']
            )
        
        return APIResponse(success=True, data=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm")
async def get_llm_config():
    """Get LLM configuration"""
    try:
        config = config_manager.get_llm_config()
        config_dict = config.dict()
        
        # Mask API key
        if config_dict.get('api_key'):
            config_dict['api_key'] = mask_sensitive_value(config_dict['api_key'])
        
        return APIResponse(success=True, data=config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm")
async def save_llm_config(config: LLMConfig):
    """Save LLM configuration"""
    try:
        success = config_manager.save_llm_config(config)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="LLM configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/edit-file")
async def get_edit_file_config():
    """Get edit file configuration"""
    try:
        config = config_manager.get_edit_file_config()
        config_dict = config.dict()
        
        # Mask API key
        if config_dict.get('api_key'):
            config_dict['api_key'] = mask_sensitive_value(config_dict['api_key'])
        
        return APIResponse(success=True, data=config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edit-file")
async def save_edit_file_config(config: EditFileConfig):
    """Save edit file configuration"""
    try:
        success = config_manager.save_edit_file_config(config)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="Edit file configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search-keys")
async def get_search_keys():
    """Get search API keys"""
    try:
        config = config_manager.get_search_keys()
        config_dict = config.dict()
        
        # Mask API keys
        if config_dict.get('exa_api_key'):
            config_dict['exa_api_key'] = mask_sensitive_value(config_dict['exa_api_key'])
        if config_dict.get('serpapi_api_key'):
            config_dict['serpapi_api_key'] = mask_sensitive_value(config_dict['serpapi_api_key'])
        
        return APIResponse(success=True, data=config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search-keys")
async def save_search_keys(config: SearchKeysConfig):
    """Save search API keys"""
    try:
        success = config_manager.save_search_keys(config)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="Search keys saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deep-research/agent")
async def get_deep_research_agent_config():
    """Get deep research agent configuration"""
    try:
        config = config_manager.get_deep_research_agent_config()
        config_dict = config.dict()
        
        # Mask API key
        if config_dict.get('api_key'):
            config_dict['api_key'] = mask_sensitive_value(config_dict['api_key'])
        
        return APIResponse(success=True, data=config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deep-research/agent")
async def save_deep_research_agent_config(config: DeepResearchAgentConfig):
    """Save deep research agent configuration"""
    try:
        success = config_manager.save_deep_research_agent_config(config)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="Deep research agent configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deep-research/search")
async def get_deep_research_search_config():
    """Get deep research search configuration"""
    try:
        config = config_manager.get_deep_research_search_config()
        config_dict = config.dict()
        
        # Mask API key
        if config_dict.get('summarizer_api_key'):
            config_dict['summarizer_api_key'] = mask_sensitive_value(config_dict['summarizer_api_key'])
        
        return APIResponse(success=True, data=config_dict)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deep-research/search")
async def save_deep_research_search_config(config: DeepResearchSearchConfig):
    """Save deep research search configuration"""
    try:
        success = config_manager.save_deep_research_search_config(config)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="Deep research search configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp")
async def get_mcp_config():
    """Get MCP servers configuration"""
    try:
        servers = config_manager.get_mcp_config()
        return APIResponse(success=True, data={'mcpServers': servers})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/mcp")
async def update_mcp_config(servers: Dict[str, Any]):
    """Update MCP servers configuration"""
    try:
        # Support both formats: {'mcpServers': {...}} and direct {...}
        if 'mcpServers' in servers:
            servers = servers['mcpServers']
        success = config_manager.save_mcp_config(servers)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="MCP servers configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/mcp/servers")
async def add_mcp_server(server: MCPServerConfig):
    """Add a new MCP server"""
    try:
        success = config_manager.add_mcp_server(
            server.name,
            server.dict(exclude={'name'})
        )
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add server")
        
        return APIResponse(
            success=True,
            message="MCP server added successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/mcp/servers/{server_name}")
async def remove_mcp_server(server_name: str):
    """Remove an MCP server"""
    try:
        success = config_manager.remove_mcp_server(server_name)
        if not success:
            raise HTTPException(status_code=404, detail="Server not found")
        
        return APIResponse(
            success=True,
            message="MCP server removed successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/edgeone-pages")
async def get_edgeone_pages_config():
    """Get EdgeOne Pages configuration"""
    try:
        config = config_manager.get_edgeone_pages_config()
        return APIResponse(success=True, data=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/edgeone-pages")
async def update_edgeone_pages_config(config: EdgeOnePagesConfig):
    """Update EdgeOne Pages configuration"""
    try:
        success = config_manager.save_edgeone_pages_config(config.dict())
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="EdgeOne Pages configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deep-research")
async def get_deep_research_full_config():
    """Get complete deep research configuration"""
    try:
        config = config_manager.get_deep_research_config()
        return APIResponse(success=True, data=config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/deep-research")
async def update_deep_research_full_config(config: DeepResearchConfig):
    """Update complete deep research configuration"""
    try:
        success = config_manager.save_deep_research_config(config.dict())
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save configuration")
        
        return APIResponse(
            success=True,
            message="Deep research configuration saved successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def list_available_models():
    """List available LLM models"""
    return APIResponse(
        success=True,
        data={
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
    )


@router.get("/status")
async def get_config_status():
    """Get configuration status (which services are configured)"""
    try:
        llm_config = config_manager.get_llm_config()
        search_keys = config_manager.get_search_keys()
        dr_config = config_manager.get_deep_research_config()
        
        status = {
            'llm_configured': bool(llm_config.api_key and llm_config.model),
            'search_configured': bool(search_keys.exa_api_key or search_keys.serpapi_api_key),
            'deep_research_configured': bool(dr_config.get('researcher', {}).get('api_key'))
        }
        
        return APIResponse(success=True, data=status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
