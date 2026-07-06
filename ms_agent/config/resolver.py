# Copyright (c) ModelScope Contributors. All rights reserved.
"""ConfigResolver — multi-layer config merging.

Merges config from five layers (later wins):
  1. Framework defaults   (ms_agent/agent/agent.yaml)
  2. Global user settings (~/.ms_agent/settings.json)
  3. Agent config         (the agent.yaml / workflow.yaml specified by the user)
  4. Project patch        (<project>/.ms-agent/config.yaml)
  5. Session overrides    (runtime overrides, e.g. model switch in a session)

MCP/Skills merge semantics:
  - Union by name, project-level overrides global on conflict
  - Each entry carries an `enabled` flag

Also provides MCP-specific resolution via MCPConfigManager (Playground F7).

This class does NOT replace Config.from_task(). CLI mode continues to use
Config.from_task() directly. ConfigResolver is for server/UI scenarios
where layered config is needed.
"""
from __future__ import annotations

import copy
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from omegaconf import DictConfig, ListConfig, OmegaConf

from ms_agent.config.mcp_manager import MCPConfigManager
from ms_agent.config.mcp_schema import (
    ResolvedMCPConfig,
    collect_builtin_tool_names,
    merge_mcp_layers,
    normalize_mcp_servers_layer,
)
from ms_agent.utils import get_logger
from ms_agent.plugins.config_manager import PluginConfigManager

logger = get_logger()

_FRAMEWORK_DEFAULTS_PATH = (
    Path(__file__).parent.parent / 'agent' / 'agent.yaml'
)

GLOBAL_SETTINGS_FILE = 'settings.json'
GLOBAL_MCP_FILE = 'mcp.json'
GLOBAL_SKILLS_FILE = 'skills.json'
PROJECT_CONFIG_FILE = 'config.yaml'
PROJECT_MCP_FILE = 'mcp.json'
PROJECT_SKILLS_FILE = 'skills.json'


class ConfigResolver:
    """Multi-layer config resolver for server/UI and Playground scenarios."""

    def __init__(
        self,
        global_dir: Union[str, Path] = '~/.ms_agent',
        project_root: Union[str, Path, None] = None,
        agent_config: DictConfig | ListConfig | None = None,
        mcp_manager: MCPConfigManager | None = None,
    ) -> None:
        self._global_dir = Path(global_dir).expanduser()
        self.project_root = (
            Path(project_root).expanduser() if project_root else None
        )
        self.agent_config = agent_config
        self.mcp_manager = mcp_manager or MCPConfigManager(
            self._global_dir, self.project_root)
        self.plugin_manager = PluginConfigManager(
            self._global_dir, self.project_root)

    @property
    def global_root(self) -> Path:
        """Alias for the global config directory (Playground MCP APIs)."""
        return self._global_dir

    def resolve(
        self,
        agent_config: Union[DictConfig, str, None] = None,
        project_path: Optional[str] = None,
        session_overrides: Optional[Dict[str, Any]] = None,
    ) -> DictConfig:
        """Merge configs from all layers.

        Args:
            agent_config: An already-loaded DictConfig, a path to an
                agent.yaml file, or None to use framework defaults only.
            project_path: The project's workspace root. If provided,
                reads <project_path>/.ms-agent/config.yaml as a patch.
            session_overrides: Runtime overrides (e.g. model switch).

        Returns:
            The merged DictConfig ready for AgentLoader.build().
        """
        layers: List[DictConfig] = []

        layers.append(self._load_framework_defaults())

        global_settings = self._load_global_settings()
        if global_settings:
            layers.append(global_settings)

        effective_agent_config = (
            agent_config if agent_config is not None else self.agent_config
        )
        if effective_agent_config is not None:
            if isinstance(effective_agent_config, str):
                effective_agent_config = OmegaConf.load(effective_agent_config)
            layers.append(effective_agent_config)

        effective_project_path = project_path
        if effective_project_path is None and self.project_root is not None:
            effective_project_path = str(self.project_root)

        if effective_project_path:
            project_patch = self._load_project_patch(effective_project_path)
            if project_patch:
                layers.append(project_patch)

        if session_overrides:
            layers.append(OmegaConf.create(session_overrides))

        merged = self._merge_layers(layers)

        merged = self._merge_mcp(merged, effective_project_path)
        merged = self._merge_skills(merged, effective_project_path)
        merged = self._merge_plugins(merged, effective_project_path)

        from ms_agent.config.config import Config
        merged = Config.fill_missing_fields(merged)

        return merged

    def resolve_mcp(
        self,
        session_id: str | None = None,
        session_override: Dict[str, Dict[str, Any]] | None = None,
    ) -> ResolvedMCPConfig:
        """Merge framework → global → agent.yaml → project → session MCP layers."""
        del session_id  # reserved for Phase 3 session.json

        from ms_agent.config.config import Config

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
        from ms_agent.config.config import Config

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

    # -- layer loading --

    def _load_framework_defaults(self) -> DictConfig:
        if _FRAMEWORK_DEFAULTS_PATH.exists():
            return OmegaConf.load(str(_FRAMEWORK_DEFAULTS_PATH))
        return OmegaConf.create({})

    def _load_global_settings(self) -> Optional[DictConfig]:
        settings_file = self._global_dir / GLOBAL_SETTINGS_FILE
        if not settings_file.exists():
            return None
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return self._settings_to_agent_config(data)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f'Failed to load global settings: {e}')
            return None

    def _load_project_patch(self, project_path: str) -> Optional[DictConfig]:
        patch_file = Path(project_path) / '.ms-agent' / PROJECT_CONFIG_FILE
        if not patch_file.exists():
            return None
        try:
            return OmegaConf.load(str(patch_file))
        except Exception as e:
            logger.warning(f'Failed to load project config patch: {e}')
            return None

    # -- merging --

    @staticmethod
    def _merge_layers(layers: List[DictConfig]) -> DictConfig:
        if not layers:
            return OmegaConf.create({})
        result = layers[0]
        for layer in layers[1:]:
            result = OmegaConf.merge(result, layer)
        return result

    def _merge_mcp(
        self, config: DictConfig, project_path: Optional[str]
    ) -> DictConfig:
        global_mcp = self._load_json_safe(
            self._global_dir / GLOBAL_MCP_FILE
        )
        project_mcp = {}
        if project_path:
            project_mcp = self._load_json_safe(
                Path(project_path) / '.ms-agent' / PROJECT_MCP_FILE
            )

        if not global_mcp and not project_mcp:
            return config

        merged = merge_mcp_configs(global_mcp, project_mcp)
        if merged:
            OmegaConf.update(config, '_merged_mcp', merged, merge=True)
        return config

    def _merge_plugins(
        self, config: DictConfig, project_path: Optional[str]
    ) -> DictConfig:
        manager = (
            PluginConfigManager(self._global_dir, project_path)
            if project_path
            else self.plugin_manager
        )
        records = manager.load_merged(project_path)
        if not records:
            return config

        payload = {'plugins': [record.to_dict() | {'scope': record.scope}
                              for record in records]}
        OmegaConf.update(config, '_merged_plugins', payload, merge=True)

        enabled_paths = [
            record.path for record in records
            if record.enabled and record.path
        ]
        existing = []
        if hasattr(config, 'plugins') and config.plugins:
            existing = [str(item) for item in config.plugins]
        merged_paths = existing + [p for p in enabled_paths if p not in existing]
        if merged_paths:
            OmegaConf.update(config, 'plugins', merged_paths, merge=True)
        return config

    def _merge_skills(
        self, config: DictConfig, project_path: Optional[str]
    ) -> DictConfig:
        global_skills = self._load_json_safe(
            self._global_dir / GLOBAL_SKILLS_FILE
        )
        project_skills = {}
        if project_path:
            project_skills = self._load_json_safe(
                Path(project_path) / '.ms-agent' / PROJECT_SKILLS_FILE
            )

        if not global_skills and not project_skills:
            return config

        merged = merge_skills_configs(global_skills, project_skills)
        if merged:
            OmegaConf.update(config, '_merged_skills', merged, merge=True)
        return config

    # -- helpers --

    @staticmethod
    def _settings_to_agent_config(settings: Dict[str, Any]) -> DictConfig:
        """Convert global settings.json structure to agent config shape.

        settings.json has keys like 'llm', 'theme', 'output_dir'.
        We extract the parts that map to agent config fields.
        """
        agent_fields: Dict[str, Any] = {}
        if 'llm' in settings:
            llm = settings['llm']
            agent_llm: Dict[str, Any] = {}
            if 'provider' in llm:
                agent_llm['service'] = llm['provider']
            if 'model' in llm:
                agent_llm['model'] = llm['model']
            if 'api_key' in llm and llm['api_key']:
                service = llm.get('provider', 'modelscope')
                agent_llm[f'{service}_api_key'] = llm['api_key']
            if 'base_url' in llm and llm['base_url']:
                service = llm.get('provider', 'modelscope')
                agent_llm[f'{service}_base_url'] = llm['base_url']
            if 'temperature' in llm and llm.get('temperature_enabled'):
                agent_fields.setdefault('generation_config', {})
                agent_fields['generation_config']['temperature'] = llm[
                    'temperature'
                ]
            if 'max_tokens' in llm and llm['max_tokens']:
                agent_fields.setdefault('generation_config', {})
                agent_fields['generation_config']['max_tokens'] = llm[
                    'max_tokens'
                ]
            if agent_llm:
                agent_fields['llm'] = agent_llm
        if 'output_dir' in settings:
            agent_fields['output_dir'] = settings['output_dir']
        if 'personalization' in settings:
            p = settings['personalization']
            p_fields: Dict[str, Any] = {}
            if p.get('global_instruction'):
                p_fields['global_instruction'] = p['global_instruction']
            if 'memory_enabled' in p:
                p_fields['memory_enabled'] = p['memory_enabled']
            if 'memory_backend' in p:
                p_fields['memory_backend'] = p['memory_backend']
            if p_fields:
                agent_fields['personalization'] = p_fields
        return OmegaConf.create(agent_fields)

    @staticmethod
    def _load_json_safe(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


def merge_mcp_configs(
    global_mcp: Dict[str, Any],
    project_mcp: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge global and project MCP server configs.

    - Union by server name
    - Project-level overrides global on name conflict
    - Each entry carries 'enabled' (defaults to True)
    - Returns {"servers": {name: config, ...}}
    """
    global_servers = _extract_mcp_servers(global_mcp)
    project_servers = _extract_mcp_servers(project_mcp)

    merged: Dict[str, Any] = {}
    for name, cfg in global_servers.items():
        entry = deepcopy(cfg)
        entry.setdefault('enabled', True)
        entry['_scope'] = 'global'
        merged[name] = entry

    for name, cfg in project_servers.items():
        entry = deepcopy(cfg)
        entry.setdefault('enabled', True)
        entry['_scope'] = 'project'
        merged[name] = entry

    return {'servers': merged} if merged else {}


def merge_skills_configs(
    global_skills: Dict[str, Any],
    project_skills: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge global and project skills configs.

    - sources: project sources appended after global (higher priority)
    - disabled: union of both
    - Each skill entry carries 'enabled' (defaults to True)
    """
    global_sources = global_skills.get('sources', [])
    project_sources = project_skills.get('sources', [])

    global_disabled = set(global_skills.get('disabled', []))
    project_disabled = set(project_skills.get('disabled', []))
    all_disabled = global_disabled | project_disabled

    global_enabled_map = {
        s.get('name', s.get('path', '')): s.get('enabled', True)
        for s in global_sources
        if isinstance(s, dict)
    }
    project_enabled_map = {
        s.get('name', s.get('path', '')): s.get('enabled', True)
        for s in project_sources
        if isinstance(s, dict)
    }

    merged_sources = list(global_sources) + [
        s for s in project_sources if s not in global_sources
    ]

    return {
        'sources': merged_sources,
        'disabled': sorted(all_disabled),
        '_enabled_map': {**global_enabled_map, **project_enabled_map},
    }


def _extract_mcp_servers(mcp_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle both {"mcpServers": {...}} and flat {name: config} formats."""
    if 'mcpServers' in mcp_data:
        return mcp_data['mcpServers']
    if 'servers' in mcp_data:
        return mcp_data['servers']
    return {
        k: v
        for k, v in mcp_data.items()
        if isinstance(v, dict) and k not in ('_scope', 'enabled')
    }
