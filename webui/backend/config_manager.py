# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Configuration management for MS-Agent Web UI
Handles global settings, LLM configuration, and MCP server configuration.
"""
import os
from threading import Lock
from typing import Any, Dict, Optional

import json


class ConfigManager:
    """Manages global configuration for the Web UI"""

    DEFAULT_CONFIG = {
        'llm': {
            'provider': 'modelscope',
            'model': 'Qwen/Qwen3-235B-A22B-Instruct-2507',
            'api_key': '',
            'base_url': 'https://api-inference.modelscope.cn/v1/',
            'temperature': 0.7,
            'max_tokens': 4096
        },
        'mcp_servers': {},
        'theme': 'dark',
        'output_dir': './output'
    }

    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, 'settings.json')
        self.mcp_file = os.path.join(config_dir, 'mcp_servers.json')
        self._lock = Lock()
        self._config: Optional[Dict[str, Any]] = None
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Ensure config directory exists"""
        os.makedirs(self.config_dir, exist_ok=True)

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if self._config is not None:
            return self._config

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self._config = json.load(f)
            except Exception:
                self._config = self.DEFAULT_CONFIG.copy()
        else:
            self._config = self.DEFAULT_CONFIG.copy()

        # Load MCP servers from separate file if exists
        if os.path.exists(self.mcp_file):
            try:
                with open(self.mcp_file, 'r', encoding='utf-8') as f:
                    mcp_data = json.load(f)
                    if 'mcpServers' in mcp_data:
                        self._config['mcp_servers'] = mcp_data['mcpServers']
                    else:
                        self._config['mcp_servers'] = mcp_data
            except Exception:
                pass

        return self._config

    def _save_config(self):
        """Save configuration to file"""
        with self._lock:
            # Save main config (without mcp_servers)
            config_to_save = {
                k: v
                for k, v in self._config.items() if k != 'mcp_servers'
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2)

            # Save MCP servers to separate file (compatible with ms-agent format)
            mcp_data = {'mcpServers': self._config.get('mcp_servers', {})}
            with open(self.mcp_file, 'w', encoding='utf-8') as f:
                json.dump(mcp_data, f, indent=2)

    def get_config(self) -> Dict[str, Any]:
        """Get the full configuration"""
        return self._load_config().copy()

    def update_config(self, config: Dict[str, Any]):
        """Update the full configuration"""
        self._load_config()
        self._config.update(config)
        self._save_config()

    def get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration"""
        config = self._load_config()
        return config.get('llm', self.DEFAULT_CONFIG['llm'])

    def update_llm_config(self, llm_config: Dict[str, Any]):
        """Update LLM configuration"""
        self._load_config()
        self._config['llm'] = llm_config
        self._save_config()

    def get_mcp_config(self) -> Dict[str, Any]:
        """Get MCP servers configuration"""
        config = self._load_config()
        return {'mcpServers': config.get('mcp_servers', {})}

    def update_mcp_config(self, mcp_config: Dict[str, Any]):
        """Update MCP servers configuration"""
        self._load_config()
        if 'mcpServers' in mcp_config:
            self._config['mcp_servers'] = mcp_config['mcpServers']
        else:
            self._config['mcp_servers'] = mcp_config
        self._save_config()

    def add_mcp_server(self, name: str, server_config: Dict[str, Any]):
        """Add a new MCP server"""
        self._load_config()
        if 'mcp_servers' not in self._config:
            self._config['mcp_servers'] = {}
        self._config['mcp_servers'][name] = server_config
        self._save_config()

    def remove_mcp_server(self, name: str) -> bool:
        """Remove an MCP server"""
        self._load_config()
        if name in self._config.get('mcp_servers', {}):
            del self._config['mcp_servers'][name]
            self._save_config()
            return True
        return False

    def get_mcp_file_path(self) -> str:
        """Get the path to the MCP servers file"""
        return self.mcp_file

    def get_env_vars(self) -> Dict[str, str]:
        """Get environment variables for running agents"""
        config = self._load_config()
        llm = config.get('llm', {})

        env_vars = {}

        if llm.get('api_key'):
            provider = llm.get('provider', 'modelscope')
            if provider == 'modelscope':
                env_vars['MODELSCOPE_API_KEY'] = llm['api_key']
            elif provider == 'openai':
                env_vars['OPENAI_API_KEY'] = llm['api_key']
            elif provider == 'anthropic':
                env_vars['ANTHROPIC_API_KEY'] = llm['api_key']

        if llm.get('base_url'):
            env_vars['OPENAI_BASE_URL'] = llm['base_url']

        return env_vars
