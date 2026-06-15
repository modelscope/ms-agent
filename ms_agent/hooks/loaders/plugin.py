"""Plugin hooks/hooks.json loader (F9)."""

from __future__ import annotations

from pathlib import Path

from ms_agent.hooks.loaders.claude import ClaudeSettingsLoader
from ms_agent.hooks.registry import HookRegistry


class PluginHooksLoader:
    @staticmethod
    def load_plugin(
        plugin_root: str | Path,
        *,
        project_path: str,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        root = Path(plugin_root)
        hooks_path = root / 'hooks' / 'hooks.json'
        if not hooks_path.is_file():
            return HookRegistry(_index={})
        return ClaudeSettingsLoader.parse_hooks_file(
            hooks_path,
            plugin_root=str(root),
            project_path=project_path,
            enabled_executors=enabled_executors,
        )
