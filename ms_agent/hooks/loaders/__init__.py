"""Hook loaders package."""

from ms_agent.hooks.loaders.claude import ClaudeSettingsLoader
from ms_agent.hooks.loaders.cursor import CursorHooksLoader
from ms_agent.hooks.loaders.hermes import HermesShellLoader
from ms_agent.hooks.loaders.native import NativeJsonLoader, NativeYamlLoader
from ms_agent.hooks.loaders.plugin import PluginHooksLoader

__all__ = [
    'ClaudeSettingsLoader',
    'CursorHooksLoader',
    'HermesShellLoader',
    'NativeJsonLoader',
    'NativeYamlLoader',
    'PluginHooksLoader',
]
