"""Installed plugin index — disk records plus in-memory manifest cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from ms_agent.plugins.config_manager import PluginConfigManager, PluginScope
from ms_agent.plugins.manifest import PluginManifest, PluginError, normalize_plugin_id
from ms_agent.plugins.types import PluginRecord

PluginScopeArg = Literal['global', 'project', 'merged']


class PluginRegistry:
    """Facade over ``plugins.json`` with optional parsed manifest cache."""

    def __init__(
        self,
        config_manager: PluginConfigManager | None = None,
        *,
        global_root: str | Path = '~/.ms_agent',
        project_root: str | Path | None = None,
    ) -> None:
        self.global_root = Path(global_root).expanduser()
        self.config_manager = config_manager or PluginConfigManager(
            self.global_root,
            project_root,
        )
        self._manifest_cache: dict[str, PluginManifest] = {}

    def list_records(self, scope: PluginScopeArg = 'merged') -> list[PluginRecord]:
        return self.config_manager.list(scope)  # type: ignore[arg-type]

    def get_record(
        self,
        plugin_id: str,
        scope: PluginScopeArg = 'merged',
    ) -> PluginRecord | None:
        return self.config_manager.get(plugin_id, scope)  # type: ignore[arg-type]

    def is_installed(self, plugin_id: str, scope: PluginScopeArg = 'merged') -> bool:
        return self.get_record(plugin_id, scope) is not None

    def get_manifest(
        self,
        plugin_id: str,
        *,
        scope: PluginScopeArg = 'merged',
        use_cache: bool = True,
    ) -> PluginManifest | None:
        if use_cache and plugin_id in self._manifest_cache:
            return self._manifest_cache[plugin_id]
        record = self.get_record(plugin_id, scope)
        if record is None or not record.path:
            return None
        try:
            manifest = PluginManifest.parse(record.path, record=record)
        except PluginError:
            return None
        self._manifest_cache[plugin_id] = manifest
        return manifest

    def invalidate(self, plugin_id: str | None = None) -> None:
        if plugin_id is None:
            self._manifest_cache.clear()
            return
        self._manifest_cache.pop(plugin_id, None)

    def managed_plugin_paths(self, project_path: str | None = None) -> set[str]:
        """Resolved install paths for deduplicating legacy ``config.plugins``."""
        records = self.config_manager.load_merged(project_path)
        paths: set[str] = set()
        for record in records:
            if record.path:
                paths.add(str(Path(record.path).expanduser().resolve()))
        return paths

    def managed_plugin_ids(self, project_path: str | None = None) -> set[str]:
        return {record.id for record in self.config_manager.load_merged(project_path)}
