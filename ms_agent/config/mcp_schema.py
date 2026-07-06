# Copyright (c) ModelScope Contributors. All rights reserved.
"""Normalized MCP configuration schema and merge helpers."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from omegaconf import DictConfig, ListConfig, OmegaConf

MCPSource = Literal['global', 'project', 'agent_yaml', 'plugin', 'session']

# Connection-related fields kept when normalizing agent.yaml / JSON entries.
MCP_CONNECTION_FIELDS = frozenset({
    'enabled',
    'transport',
    'type',
    'command',
    'args',
    'url',
    'env',
    'headers',
    'timeout',
    'include',
    'exclude',
    'source',
    'meta',
    'session_kwargs',
    'httpx_client_factory',
    'encoding',
    'encoding_error_handler',
    'sse_read_timeout',
})

# YAML / agent metadata stripped during normalization.
MCP_STRIP_FIELDS = frozenset({
    'mcp',
    'implementation',
    'trust_remote_code',
    '_removed',
})


@dataclass
class ResolvedMCPConfig:
    """Normalized multi-layer MCP configuration."""

    mcp_servers: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def to_mcp_json(self) -> Dict[str, Any]:
        return {'mcpServers': copy.deepcopy(self.mcp_servers)}

    def enabled_servers(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: cfg
            for name, cfg in self.mcp_servers.items()
            if cfg.get('enabled', True)
        }


def _coerce_entry_dict(entry: Any) -> Optional[Dict[str, Any]]:
    if isinstance(entry, (DictConfig, ListConfig)):
        container = OmegaConf.to_container(entry, resolve=True)
        return container if isinstance(container, dict) else None
    if isinstance(entry, dict):
        return entry
    return None


def normalize_mcp_server_entry(
    entry: Dict[str, Any],
    *,
    source: MCPSource = 'global',
    default_enabled: bool = True,
) -> Optional[Dict[str, Any]]:
    """Normalize a single MCP server entry for merge / runtime consumption.

    Returns ``None`` when the entry should not appear in ``mcpServers`` (e.g.
    ``mcp: false`` in agent.yaml).
    """
    if not entry:
        return None
    coerced = _coerce_entry_dict(entry)
    if coerced is None:
        return None
    entry = coerced
    if entry.get('mcp') is False:
        return None
    if entry.get('_removed'):
        return {'enabled': False, 'source': source}

    normalized: Dict[str, Any] = {}
    for key, value in entry.items():
        if key in MCP_STRIP_FIELDS:
            continue
        if key in MCP_CONNECTION_FIELDS:
            normalized[key] = copy.deepcopy(value)

    if 'enabled' not in normalized:
        normalized['enabled'] = default_enabled
    normalized['source'] = normalized.get('source', source)
    return normalized


def normalize_mcp_servers_layer(
    servers: Optional[Dict[str, Any]],
    *,
    source: MCPSource,
) -> Dict[str, Dict[str, Any]]:
    if not servers:
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    for name, entry in servers.items():
        coerced = _coerce_entry_dict(entry)
        if coerced is None:
            continue
        normalized = normalize_mcp_server_entry(coerced, source=source)
        if normalized is not None:
            result[name] = normalized
    return result


def merge_mcp_server_entry(
    base: Dict[str, Any],
    override: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge two server entries; ``override`` wins on explicit fields."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in MCP_STRIP_FIELDS:
            continue
        if key == 'meta' and isinstance(value, dict):
            merged_meta = dict(merged.get('meta') or {})
            merged_meta.update(value)
            merged['meta'] = merged_meta
        else:
            merged[key] = copy.deepcopy(value)

    # enabled: only override when explicitly set in the patch layer
    if 'enabled' not in override and 'enabled' in base:
        merged['enabled'] = base['enabled']
    return merged


def merge_mcp_layers(*layers: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Union merge by server name; later layers override earlier ones."""
    merged: Dict[str, Dict[str, Any]] = {}
    for layer in layers:
        for name, entry in layer.items():
            if name in merged:
                merged[name] = merge_mcp_server_entry(merged[name], entry)
            else:
                merged[name] = copy.deepcopy(entry)
    return merged


def collect_builtin_tool_names(
    agent_config: DictConfig | ListConfig | None,
) -> set[str]:
    """Names declared as built-in tools (``mcp: false``) in agent.yaml.

    These entries must not appear in merged ``mcpServers`` even when a lower
    layer (e.g. global settings) defines a same-named MCP server.  The built-in
    implementation is provided via ``ToolManager.extra_tools`` instead.
    """
    if agent_config is None or not hasattr(agent_config, 'tools'):
        return set()
    tools = agent_config.tools
    container = OmegaConf.to_container(tools, resolve=True)
    if not isinstance(container, dict):
        return set()
    return {
        name
        for name, entry in container.items()
        if isinstance(entry, dict) and entry.get('mcp') is False
    }


def connection_params_for_client(server: Dict[str, Any]) -> Dict[str, Any]:
    """Extract connect kwargs from a normalized server entry."""
    params: Dict[str, Any] = {}
    for key in MCP_CONNECTION_FIELDS:
        if key in ('enabled', 'source', 'meta'):
            continue
        if key in server:
            params[key] = copy.deepcopy(server[key])
    return params
