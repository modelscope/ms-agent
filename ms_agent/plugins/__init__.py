"""Plugin compatibility layer for container-style community plugins.

Keep this package initializer intentionally lightweight. Several core modules
import plugin submodules during config loading, and importing runtime/loader
here would pull hooks and agent modules early enough to create circular imports.
"""

__all__ = [
    'config_manager',
    'dependencies',
    'installer',
    'loader',
    'manifest',
    'registry',
    'runtime',
    'types',
    'user_config',
]
