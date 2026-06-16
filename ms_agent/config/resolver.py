# Copyright (c) ModelScope Contributors. All rights reserved.
"""Multi-layer configuration resolver for Playground / WebUI."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

from omegaconf import DictConfig, ListConfig

from ms_agent.config.config import Config
from ms_agent.config.mcp_manager import MCPConfigManager
from ms_agent.config.mcp_schema import (
    ResolvedMCPConfig,
    collect_builtin_tool_names,
    merge_mcp_layers,
    normalize_mcp_servers_layer,
)


class ConfigResolver:
    """Resolve layered MCP configuration for runtime consumption."""

    def __init__(
        self,
        global_root: Path | str,
        project_root: Path | str | None = None,
        agent_config: DictConfig | ListConfig | None = None,
        mcp_manager: MCPConfigManager | None = None,
    ):
        self.global_root = Path(global_root).expanduser()
        self.project_root = (
            Path(project_root).expanduser() if project_root else None
        )
        self.agent_config = agent_config
        self.mcp_manager = mcp_manager or MCPConfigManager(
            self.global_root, self.project_root)

    def resolve_mcp(
        self,
        session_id: str | None = None,
        session_override: Dict[str, Dict[str, Any]] | None = None,
    ) -> ResolvedMCPConfig:
        """Merge framework → global → agent.yaml → project → session layers."""
        del session_id  # reserved for Phase 3 session.json

        global_layer = normalize_mcp_servers_layer(
            self.mcp_manager.list('global'),
            source='global',
        )
        agent_yaml_layer: Dict[str, Dict[str, Any]] = {}
        if self.agent_config is not None:
            raw = Config.convert_mcp_servers_to_json(self.agent_config)
            agent_yaml_layer = normalize_mcp_servers_layer(
                raw.get('mcpServers'),
                source='agent_yaml',
            )

        project_layer = normalize_mcp_servers_layer(
            self.mcp_manager.list('project'),
            source='project',
        )

        session_layer = normalize_mcp_servers_layer(
            session_override,
            source='session',
        )

        merged = merge_mcp_layers(
            {},
            global_layer,
            agent_yaml_layer,
            project_layer,
            session_layer,
        )
        for name in collect_builtin_tool_names(self.agent_config):
            merged.pop(name, None)
        return ResolvedMCPConfig(mcp_servers=merged)

    def resolve_mcp_all_layers(
        self,
        session_override: Dict[str, Dict[str, Any]] | None = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Return merged servers including disabled entries (for UI listing)."""
        global_layer = normalize_mcp_servers_layer(
            self.mcp_manager.list('global'), source='global')
        agent_yaml_layer: Dict[str, Dict[str, Any]] = {}
        if self.agent_config is not None:
            raw = Config.convert_mcp_servers_to_json(self.agent_config)
            agent_yaml_layer = normalize_mcp_servers_layer(
                raw.get('mcpServers'), source='agent_yaml')
        project_layer = normalize_mcp_servers_layer(
            self.mcp_manager.list('project'), source='project')
        session_layer = normalize_mcp_servers_layer(
            session_override, source='session')
        merged = merge_mcp_layers(
            global_layer,
            agent_yaml_layer,
            project_layer,
            session_layer,
        )
        for name in collect_builtin_tool_names(self.agent_config):
            merged.pop(name, None)
        return merged

    def with_agent_config(
        self,
        agent_config: DictConfig | ListConfig | None,
    ) -> 'ConfigResolver':
        clone = copy.copy(self)
        clone.agent_config = agent_config
        return clone
