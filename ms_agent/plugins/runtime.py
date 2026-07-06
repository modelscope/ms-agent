from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from ms_agent.plugins.config_manager import PluginConfigManager
from ms_agent.plugins.agents import PluginAgentRegistry
from ms_agent.plugins.installer import PluginInstaller
from ms_agent.plugins.loader import (
    PluginLoadContext,
    PluginLoadResult,
    PluginLoader,
)
from ms_agent.plugins.manifest import PluginManifest, PluginError
from ms_agent.plugins.registry import PluginRegistry
from ms_agent.plugins.types import PluginRecord, component_status_dict
from ms_agent.utils import get_logger

logger = get_logger()
_MISSING = object()


@dataclass
class PluginRuntime:
    config_manager: PluginConfigManager | None = None
    registry: PluginRegistry | None = None
    global_root: str | Path = '~/.ms_agent'
    skill_runtime: Any | None = None
    hook_runtime_factory: Any | None = None
    mcp_runtime: Any | None = None
    manifests: list[PluginManifest] = field(default_factory=list)
    load_result: PluginLoadResult = field(default_factory=PluginLoadResult)
    agent_registry: PluginAgentRegistry = field(default_factory=PluginAgentRegistry)
    _applied_skill_paths: set[str] = field(default_factory=set, init=False)
    _applied_mcp_names: set[str] = field(default_factory=set, init=False)
    _applied_bin_paths: set[str] = field(default_factory=set, init=False)
    _applied_settings_originals: dict[str, Any] = field(default_factory=dict, init=False)
    _project_path: str | None = field(default=None, init=False)
    _session_id: str = field(default='', init=False)
    _config: Any | None = field(default=None, init=False)
    _configured_plugin_ids: set[str] = field(default_factory=set, init=False)
    _enabled_executors: frozenset[str] = field(
        default_factory=lambda: frozenset({'command'}),
        init=False,
    )

    def __post_init__(self) -> None:
        self.global_root = Path(self.global_root).expanduser()
        if self.config_manager is None:
            self.config_manager = PluginConfigManager(self.global_root)
        if self.registry is None:
            self.registry = PluginRegistry(self.config_manager)
        self._reload_lock = asyncio.Lock()

    async def start(
        self,
        project_path: str,
        session_id: str,
        *,
        config: Any | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> None:
        async with self._reload_lock:
            self._start_unlocked(
                project_path,
                session_id,
                config=config,
                enabled_executors=enabled_executors,
            )

    def start_sync(
        self,
        project_path: str,
        session_id: str,
        *,
        config: Any | None = None,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> None:
        self._start_unlocked(
            project_path,
            session_id,
            config=config,
            enabled_executors=enabled_executors,
        )

    def _start_unlocked(
        self,
        project_path: str,
        session_id: str,
        *,
        config: Any | None,
        enabled_executors: frozenset[str],
    ) -> None:
        records = self._records_from_config(config, project_path)
        self.registry.invalidate()  # type: ignore[union-attr]
        self._project_path = project_path
        self._session_id = session_id
        self._config = config
        self._enabled_executors = enabled_executors
        self._configured_plugin_ids = {record.id for record in records}
        manifests: list[PluginManifest] = []
        for record in records:
            if not record.enabled:
                continue
            try:
                manifests.append(PluginManifest.parse(record.path, record=record))
            except PluginError as exc:
                logger.warning('Failed to parse plugin %s: %s', record.id, exc)

        ctx = PluginLoadContext(
            project_path=project_path,
            session_id=session_id,
            enabled_executors=enabled_executors,
            plugin_data_root=self.global_root / 'plugins' / 'data',
        )
        self.manifests = manifests
        self.load_result = PluginLoader.load_all(manifests, ctx)
        self.agent_registry.rebuild(self.load_result.agent_defs)
        if config is not None:
            self.apply_to_config(config)
            self._sync_skill_runtime(config)

    def apply_to_config(self, config: Any) -> None:
        self._remove_applied_skill_sources(config)
        self._remove_applied_mcp_servers(config)
        self._remove_plugin_owned_mcp_servers(config, self._configured_plugin_ids)
        self._remove_applied_bin_paths(config)
        self._revert_applied_settings(config)

        if self.load_result.skill_sources:
            if not hasattr(config, 'skills') or config.skills is None:
                config.skills = OmegaConf.create({'sources': []})
            if not hasattr(config.skills, 'sources') or config.skills.sources is None:
                config.skills.sources = []
            existing = {
                _skill_source_path(source)
                for source in config.skills.sources
            }
            for source in self.load_result.skill_sources:
                if source.path in existing:
                    continue
                config.skills.sources.append({
                    'type': source.type.value,
                    'path': source.path,
                    'enabled': source.enabled,
                    'origin': source.origin,
                    'plugin_id': source.plugin_id,
                    'capability': source.capability,
                })
                existing.add(str(source.path))
                self._applied_skill_paths.add(str(source.path))

        if self.load_result.mcp_servers:
            if not hasattr(config, 'tools') or config.tools is None:
                config.tools = OmegaConf.create({})
            current = {}
            if hasattr(config, '_merged_mcp') and config._merged_mcp:
                current = OmegaConf.to_container(
                    config._merged_mcp, resolve=True) or {}
            existing_names = set(config.tools.keys()) | set(
                (current.get('servers') or {}).keys())
            plugin_servers = dedupe_mcp_server_names(
                self.load_result.mcp_servers,
                existing_names,
            )
            self.load_result.mcp_servers = plugin_servers
            for name, server in plugin_servers.items():
                config.tools[name] = OmegaConf.create(server)

            servers = dict(current.get('servers', {}))
            servers.update(plugin_servers)
            OmegaConf.update(config, '_merged_mcp', {'servers': servers}, merge=True)
            self._applied_mcp_names = set(plugin_servers)

        for key, value in self.load_result.settings_patch.items():
            self._applied_settings_originals[key] = _snapshot_config_key(config, key)
            OmegaConf.update(config, key, value, merge=True)

        if self.load_result.bin_paths:
            if not hasattr(config, 'tools') or config.tools is None:
                config.tools = OmegaConf.create({})
            if not hasattr(config.tools, 'code_executor') or config.tools.code_executor is None:
                config.tools.code_executor = OmegaConf.create({})
            existing_bins = []
            if hasattr(config.tools.code_executor, 'plugin_bin_paths'):
                existing_bins = [
                    str(path) for path in config.tools.code_executor.plugin_bin_paths
                ]
            for path in self.load_result.bin_paths:
                if str(path) not in existing_bins:
                    existing_bins.append(str(path))
                self._applied_bin_paths.add(str(path))
            config.tools.code_executor.plugin_bin_paths = existing_bins

    def _remove_applied_skill_sources(self, config: Any) -> None:
        if not self._applied_skill_paths:
            return
        if not hasattr(config, 'skills') or not getattr(config.skills, 'sources', None):
            self._applied_skill_paths.clear()
            return
        config.skills.sources = [
            source for source in config.skills.sources
            if _skill_source_path(source) not in self._applied_skill_paths
        ]
        self._applied_skill_paths.clear()

    def _remove_applied_mcp_servers(self, config: Any) -> None:
        if not self._applied_mcp_names:
            return
        self._remove_mcp_servers_by_name(config, self._applied_mcp_names)
        self._applied_mcp_names.clear()

    def _remove_plugin_owned_mcp_servers(
        self,
        config: Any,
        plugin_ids: set[str],
    ) -> None:
        if not plugin_ids:
            return
        names: set[str] = set()
        if hasattr(config, 'tools') and config.tools is not None:
            for name, server in config.tools.items():
                server_data = _to_plain_container(server)
                if _is_plugin_server(server_data, plugin_ids):
                    names.add(str(name))
        if hasattr(config, '_merged_mcp') and config._merged_mcp:
            current = OmegaConf.to_container(config._merged_mcp, resolve=True) or {}
            for name, server in (current.get('servers') or {}).items():
                if _is_plugin_server(server, plugin_ids):
                    names.add(str(name))
        self._remove_mcp_servers_by_name(config, names)

    @staticmethod
    def _remove_mcp_servers_by_name(config: Any, names: set[str]) -> None:
        if not names:
            return
        if hasattr(config, 'tools') and config.tools is not None:
            for name in names:
                if name in config.tools:
                    del config.tools[name]
        if hasattr(config, '_merged_mcp') and config._merged_mcp:
            current = OmegaConf.to_container(config._merged_mcp, resolve=True) or {}
            servers = dict(current.get('servers', {}))
            for name in names:
                servers.pop(name, None)
            OmegaConf.update(config, '_merged_mcp', {'servers': servers}, merge=False)

    def _remove_applied_bin_paths(self, config: Any) -> None:
        if not self._applied_bin_paths:
            return
        code_executor = getattr(getattr(config, 'tools', None), 'code_executor', None)
        if code_executor is not None and hasattr(code_executor, 'plugin_bin_paths'):
            code_executor.plugin_bin_paths = [
                path for path in code_executor.plugin_bin_paths
                if str(path) not in self._applied_bin_paths
            ]
        self._applied_bin_paths.clear()

    def _revert_applied_settings(self, config: Any) -> None:
        for key, original in self._applied_settings_originals.items():
            _restore_config_key(config, key, original)
        self._applied_settings_originals.clear()

    def _sync_skill_runtime(self, config: Any) -> None:
        if self.skill_runtime is None:
            return
        if not hasattr(config, 'skills') or not config.skills:
            return
        catalog = getattr(self.skill_runtime, 'catalog', None)
        if catalog is None:
            return
        plugin_sources = list(self.load_result.skill_sources)
        if plugin_sources and hasattr(catalog, 'reload_sources'):
            catalog.reload_sources(plugin_sources)
        else:
            catalog.load_from_config(config.skills)
        if hasattr(self.skill_runtime, '_version'):
            self.skill_runtime._version += 1

    def list_all(self) -> list[dict[str, Any]]:
        loaded = {manifest.plugin_id: manifest for manifest in self.manifests}
        items: list[dict[str, Any]] = []
        for record in self.config_manager.list('merged'):  # type: ignore[union-attr]
            manifest = loaded.get(record.id)
            if manifest is None:
                items.append({
                    'plugin_id': record.id,
                    'enabled': record.enabled,
                    'scope': record.scope,
                    'path': record.path,
                    'status': 'disabled' if not record.enabled else 'error',
                    'capabilities': [],
                    'capabilities_status': {},
                })
                continue
            status = 'ready' if record.enabled else 'disabled'
            items.append({
                'plugin_id': manifest.plugin_id,
                'name': manifest.name,
                'version': manifest.version,
                'description': manifest.description,
                'enabled': record.enabled,
                'scope': record.scope,
                'path': str(manifest.root),
                'format': manifest.format.value,
                'capabilities': sorted(manifest.capabilities),
                'status': status,
                'capabilities_status': component_status_dict(manifest.components),
                'source': record.to_dict().get('source', {}),
                'installed_at': record.installed_at,
                'commands': [
                    cmd.__dict__ for cmd in self.load_result.command_defs
                    if cmd.plugin_id == manifest.plugin_id
                ],
                'agents': [
                    agent for agent in self.agent_registry.list_all()
                    if agent['plugin_id'] == manifest.plugin_id
                ],
                'agent_defs': [
                    agent.__dict__ for agent in self.load_result.agent_defs
                    if agent.plugin_id == manifest.plugin_id
                ],
                'bin_paths': [
                    str(path) for path in self.load_result.bin_paths
                    if str(path).startswith(str(manifest.root))
                ],
                'settings_patch': self.load_result.settings_patch,
                'user_config_schema': (manifest.raw or {}).get('userConfig') or {},
                'unsupported': [
                    item.__dict__ for item in self.load_result.unsupported
                    if item.capability in manifest.components
                ],
            })
        return items

    async def toggle(
        self,
        plugin_id: str,
        enabled: bool,
        *,
        scope: str = 'global',
        project_path: str | None = None,
    ) -> None:
        self.config_manager.set_enabled(  # type: ignore[union-attr]
            plugin_id,
            enabled,
            scope=scope,  # type: ignore[arg-type]
        )
        reload_path = project_path or self._project_path
        if reload_path is not None:
            await self.reload(
                plugin_id,
                project_path=reload_path,
                session_id=self._session_id,
                config=self._config,
            )

    async def reload(
        self,
        plugin_id: str | None = None,
        *,
        project_path: str,
        session_id: str = '',
        config: Any | None = None,
    ) -> None:
        del plugin_id
        await self.start(
            project_path,
            session_id or self._session_id,
            config=config if config is not None else self._config,
            enabled_executors=self._enabled_executors,
        )

    async def install(
        self,
        source: str,
        *,
        scope: str = 'global',
        project_path: str | None = None,
        **opts: Any,
    ) -> PluginManifest:
        installer = PluginInstaller(
            config_manager=self.config_manager,
            global_root=self.global_root,
            project_root=project_path,
        )
        return installer.install(source, scope=scope, project_path=project_path, **opts)

    def get_user_config(self, plugin_id: str) -> dict[str, Any]:
        manifest = self._manifest_for_plugin(plugin_id)
        schema = (manifest.raw or {}).get('userConfig') or {}
        data_dir = self.global_root / 'plugins' / 'data' / plugin_id
        from ms_agent.plugins.user_config import default_values, load_user_config
        values = load_user_config(data_dir)
        if not values and schema:
            values = default_values(schema)
        return {
            'plugin_id': plugin_id,
            'schema': schema,
            'values': values,
            'data_dir': str(data_dir),
        }

    def set_user_config(
        self,
        plugin_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = self._manifest_for_plugin(plugin_id)
        schema = (manifest.raw or {}).get('userConfig') or {}
        if not schema:
            raise ValueError(f'Plugin {plugin_id} has no userConfig schema')
        data_dir = self.global_root / 'plugins' / 'data' / plugin_id
        from ms_agent.plugins.user_config import save_user_config
        saved = save_user_config(data_dir, schema, values)
        if self._config is not None and self._project_path is not None:
            self._start_unlocked(
                self._project_path,
                self._session_id,
                config=self._config,
                enabled_executors=self._enabled_executors,
            )
        return {'plugin_id': plugin_id, 'values': saved}

    def _manifest_for_plugin(self, plugin_id: str) -> PluginManifest:
        manifest = next(
            (item for item in self.manifests if item.plugin_id == plugin_id),
            None,
        )
        if manifest is not None:
            return manifest
        record = self.config_manager.get(plugin_id, 'merged')  # type: ignore[union-attr]
        if record is None:
            raise KeyError(f'Plugin not found: {plugin_id}')
        return PluginManifest.parse(record.path, record=record)

    async def uninstall(
        self,
        plugin_id: str,
        *,
        scope: str = 'global',
        purge: bool = False,
    ) -> None:
        record = self.config_manager.get(  # type: ignore[union-attr]
            plugin_id,
            scope=scope,  # type: ignore[arg-type]
        )
        self.config_manager.remove(  # type: ignore[union-attr]
            plugin_id,
            scope=scope,  # type: ignore[arg-type]
        )
        if purge and record is not None:
            path = Path(record.path)
            if not _is_managed_plugin_path(
                path,
                self.global_root,
                self.config_manager.project_root if self.config_manager else None,
            ):
                raise ValueError(f'Refusing to purge unmanaged plugin path: {path}')
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)

    def _records_from_config(
        self,
        config: Any | None,
        project_path: str,
    ) -> list[PluginRecord]:
        raw_records = []
        if config is not None and hasattr(config, '_merged_plugins'):
            merged = OmegaConf.to_container(config._merged_plugins, resolve=True)
            if isinstance(merged, dict):
                raw_records = merged.get('plugins', [])
        if raw_records:
            records = [
                PluginRecord.from_dict(item, scope=item.get('scope'))
                for item in raw_records
                if isinstance(item, dict)
            ]
            return records + _legacy_plugin_records(
                config,
                records,
                project_path=project_path,
                global_root=self.global_root,
            )

        records = self.config_manager.load_merged(project_path)  # type: ignore[union-attr]
        if records:
            return records + _legacy_plugin_records(
                config,
                records,
                project_path=project_path,
                global_root=self.global_root,
            )

        legacy_records = _legacy_plugin_records(
            config,
            [],
            project_path=project_path,
            global_root=self.global_root,
        )
        if legacy_records:
            return legacy_records
        return []


def _skill_source_path(source: Any) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        return str(source.get('path', ''))
    return str(getattr(source, 'path', ''))


def _legacy_plugin_records(
    config: Any | None,
    existing: list[PluginRecord],
    *,
    project_path: str | None = None,
    global_root: Path | None = None,
) -> list[PluginRecord]:
    if config is None or not hasattr(config, 'plugins') or not config.plugins:
        return []
    registry = PluginRegistry(
        PluginConfigManager(global_root or Path('~/.ms_agent').expanduser()),
    )
    managed_paths = registry.managed_plugin_paths(project_path)
    managed_ids = registry.managed_plugin_ids(project_path)
    existing_paths = {str(Path(record.path).expanduser().resolve())
                      for record in existing if record.path}
    existing_paths |= managed_paths
    records: list[PluginRecord] = []
    for raw_path in config.plugins:
        path = Path(str(raw_path)).expanduser().resolve()
        if str(path) in existing_paths:
            continue
        if path.name in managed_ids:
            continue
        records.append(
            PluginRecord(
                id=path.name,
                path=str(path),
                enabled=True,
                source={'type': 'local', 'uri': str(raw_path)},
            ))
    return records


def _is_managed_plugin_path(
    path: Path,
    global_root: Path,
    project_root: Path | None = None,
) -> bool:
    resolved_parent = path.expanduser().resolve().parent
    allowed_roots = [
        (global_root / 'plugins').expanduser().resolve(),
    ]
    if project_root is not None:
        allowed_roots.append(
            (project_root / '.ms-agent' / 'plugins').expanduser().resolve())
    for root in allowed_roots:
        try:
            resolved_parent.relative_to(root)
            return True
        except ValueError:
            continue
    # Symlink paths resolve to the source, so also allow lexical storage paths.
    raw_parent = path.expanduser().absolute().parent
    for root in allowed_roots:
        try:
            raw_parent.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def dedupe_mcp_server_names(
    plugin_servers: dict[str, dict[str, Any]],
    existing_names: set[str],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    used = set(existing_names)
    for name, server in plugin_servers.items():
        candidate = name
        if candidate in used:
            plugin_id = server.get('plugin_id')
            if plugin_id:
                candidate = f'plugin.{plugin_id}.{name}'
        base = candidate
        suffix = 1
        while candidate in used or candidate in result:
            candidate = f'{base}.{suffix}'
            suffix += 1
        result[candidate] = server
        used.add(candidate)
    return result


def _snapshot_config_key(config: Any, key: str) -> Any:
    if not hasattr(config, key):
        return _MISSING
    value = getattr(config, key)
    if OmegaConf.is_config(value):
        return OmegaConf.to_container(value, resolve=False)
    return deepcopy(value)


def _restore_config_key(config: Any, key: str, value: Any) -> None:
    if value is _MISSING:
        if key in config:
            del config[key]
        return
    OmegaConf.update(config, key, value, merge=False)


def _to_plain_container(value: Any) -> Any:
    if OmegaConf.is_config(value):
        return OmegaConf.to_container(value, resolve=True)
    return value


def _is_plugin_server(server: Any, plugin_ids: set[str]) -> bool:
    return (
        isinstance(server, dict)
        and server.get('source') == 'plugin'
        and server.get('plugin_id') in plugin_ids
    )
