"""Build HookRuntime from agent config and multi-source loaders."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, OmegaConf

from ms_agent.hooks.executor import HookExecutor
from ms_agent.hooks.loaders.claude import ClaudeSettingsLoader
from ms_agent.hooks.loaders.cursor import CursorHooksLoader
from ms_agent.hooks.loaders.hermes import HermesShellLoader
from ms_agent.hooks.loaders.native import NativeJsonLoader, NativeYamlLoader
from ms_agent.hooks.loaders.plugin import PluginHooksLoader
from ms_agent.hooks.registry import HookRegistry
from ms_agent.hooks.runtime import HookRuntime
from ms_agent.hooks.tool_name_mapper import ToolNameMapper
from ms_agent.utils import get_logger

logger = get_logger()

_EMPTY_REGISTRY = HookRegistry(_index={})


def _empty_runtime(project_path: str = '', session_id: str = '') -> HookRuntime:
    return HookRuntime(
        registry=_EMPTY_REGISTRY,
        executor=HookExecutor(working_dir=project_path or None),
        session_id=session_id or str(uuid.uuid4()),
        project_path=project_path,
        tool_name_mapper=ToolNameMapper(),
    )


def _parse_hooks_meta(raw: dict[str, Any]) -> tuple[frozenset[str], frozenset[str], bool, str]:
    enabled_sources = frozenset(
        raw.get('enabled_sources', ['native']) or ['native'])
    enabled_executors = frozenset(
        raw.get('enabled_executors', ['command']) or ['command'])
    fail_closed = bool(raw.get('fail_closed', False))
    default_model = str(raw.get('default_model', 'qwen-plus'))
    return enabled_sources, enabled_executors, fail_closed, default_model


def build_hook_runtime(
    config: DictConfig | Any,
    *,
    session_id: str | None = None,
    plugin_hook_registries: list[Any] | None = None,
) -> HookRuntime:
    """Construct HookRuntime; returns empty runtime when hooks are not configured."""
    from ms_agent.utils.workspace_context import resolve_workspace_root

    project_path = str(resolve_workspace_root(config))
    global_ms_agent_dir = str(Path.home() / '.ms_agent')
    sid = session_id or str(uuid.uuid4())

    raw_hooks: dict[str, Any] = {}
    if hasattr(config, 'hooks') and config.hooks:
        raw_hooks = OmegaConf.to_container(config.hooks, resolve=True) or {}

    enabled_sources, enabled_executors, fail_closed, default_model = _parse_hooks_meta(
        raw_hooks)

    registry = HookRegistry(_index={})
    loaders: list[tuple[str, HookRegistry]] = []

    # Priority order (low -> high), aligned with §5.3
    if 'native' in enabled_sources:
        global_native = Path(global_ms_agent_dir) / 'hooks.yaml'
        if global_native.is_file():
            loaders.append((
                'global_native',
                NativeYamlLoader.load_file(
                    global_native,
                    enabled_executors=enabled_executors,
                ),
            ))

    if 'claude' in enabled_sources:
        claude_global = Path.home() / '.claude' / 'settings.json'
        if claude_global.is_file():
            loaders.append((
                'claude_global',
                ClaudeSettingsLoader.load_file(
                    claude_global,
                    project_path,
                    enabled_executors=enabled_executors,
                ),
            ))
        claude_project = Path(project_path) / '.claude' / 'settings.json'
        if claude_project.is_file():
            loaders.append((
                'claude_project',
                ClaudeSettingsLoader.load_file(
                    claude_project,
                    project_path,
                    enabled_executors=enabled_executors,
                ),
            ))

    if 'cursor' in enabled_sources:
        cursor_global = Path.home() / '.cursor' / 'hooks.json'
        if cursor_global.is_file():
            loaders.append((
                'cursor_global',
                CursorHooksLoader.load_file(
                    cursor_global,
                    project_path,
                    enabled_executors=enabled_executors,
                ),
            ))
        cursor_project = Path(project_path) / '.cursor' / 'hooks.json'
        if cursor_project.is_file():
            loaders.append((
                'cursor_project',
                CursorHooksLoader.load_file(
                    cursor_project,
                    project_path,
                    enabled_executors=enabled_executors,
                ),
            ))

    # agent.yaml hooks section (without meta keys) — native source, §5.3 priority 6
    if 'native' in enabled_sources:
        event_hooks = {
            k: v for k, v in raw_hooks.items()
            if k not in (
                'enabled_sources', 'enabled_executors', 'default_model',
                'fail_closed', 'allowed_http_hook_urls',
                'http_hook_allowed_env_vars',
            )
        }
        if event_hooks:
            loaders.append((
                'agent_yaml',
                HookRegistry.from_dict(
                    event_hooks,
                    enabled_executors=enabled_executors,
                    source='agent.yaml',
                ),
            ))

    if 'native' in enabled_sources:
        ms_agent_hooks_json = Path(project_path) / '.ms-agent' / 'hooks.json'
        if ms_agent_hooks_json.is_file():
            loaders.append((
                'ms_agent_json',
                NativeJsonLoader.load_file(
                    ms_agent_hooks_json,
                    enabled_executors=enabled_executors,
                ),
            ))

    if 'plugin' in enabled_sources:
        if plugin_hook_registries is not None:
            for contrib in plugin_hook_registries:
                if not contrib.registry.is_empty:
                    loaders.append((f'plugin:{contrib.plugin_id}', contrib.registry))
        else:
            plugin_roots = _discover_plugin_roots(config, project_path)
            seen_plugin_ids: set[str] = set()
            for root in plugin_roots:
                plugin_id = Path(root).name
                if plugin_id in seen_plugin_ids:
                    continue
                seen_plugin_ids.add(plugin_id)
                plugin_data_dir = Path.home() / '.ms_agent' / 'plugins' / 'data' / plugin_id
                reg = PluginHooksLoader.load_plugin(
                    root,
                    project_path=project_path,
                    plugin_data_dir=plugin_data_dir,
                    enabled_executors=enabled_executors,
                )
                if not reg.is_empty:
                    reg = reg.with_plugin_source(
                        plugin_id=Path(root).name,
                        plugin_root=str(root),
                        plugin_data_dir=str(plugin_data_dir),
                    )
                    loaders.append((f'plugin:{root}', reg))

    if 'hermes' in enabled_sources:
        hermes_cfg = Path.home() / '.hermes' / 'config.yaml'
        if hermes_cfg.is_file():
            loaders.append((
                'hermes',
                HermesShellLoader.load_file(hermes_cfg, project_path),
            ))

    for _name, reg in loaders:
        registry = registry.merge(reg)

    if registry.is_empty:
        return _empty_runtime(project_path, sid)

    working_dir = getattr(config, 'local_dir', None) or project_path
    executor = HookExecutor(
        working_dir=working_dir,
        enabled_executors=enabled_executors,
        fail_closed=fail_closed,
    )

    return HookRuntime(
        registry=registry,
        executor=executor,
        session_id=sid,
        project_path=project_path,
        tool_name_mapper=ToolNameMapper(enabled_sources=enabled_sources),
        default_model=default_model,
    )


def _discover_plugin_roots(config: Any, project_path: str) -> list[str]:
    from ms_agent.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    managed_paths = registry.managed_plugin_paths(project_path)
    managed_ids = registry.managed_plugin_ids(project_path)
    roots: list[str] = []
    seen: set[str] = set()
    plugins_dir = Path(project_path) / '.ms-agent' / 'plugins'
    if plugins_dir.is_dir():
        for child in plugins_dir.iterdir():
            if not child.is_dir():
                continue
            resolved = str(child.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            roots.append(str(child))
    if hasattr(config, 'plugins'):
        for p in (config.plugins or []):
            path = Path(str(p))
            if not path.is_absolute():
                path = Path(project_path) / path
            if not path.is_dir():
                continue
            resolved = str(path.resolve())
            if resolved in seen or resolved in managed_paths:
                continue
            if path.name in managed_ids:
                continue
            seen.add(resolved)
            roots.append(str(path))
    return roots
