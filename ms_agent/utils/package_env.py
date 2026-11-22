# Copyright (c) ModelScope Contributors. All rights reserved.
"""Package download settings shared by MCP children and agent shell commands.

Only explicitly allowed settings pass through. Application credentials remain
excluded; per-tool environment configuration takes precedence.
"""
PACKAGE_ENV_PASSTHROUGH = (
    'PIP_INDEX_URL',
    'PIP_CONFIG_FILE',
    'PIP_CACHE_DIR',
    'UV_INDEX_URL',
    'UV_DEFAULT_INDEX',
    'UV_CONFIG_FILE',
    'UV_CACHE_DIR',
    'npm_config_registry',
    'NPM_CONFIG_REGISTRY',
    'npm_config_cache',
    'NPM_CONFIG_CACHE',
    'npm_config_userconfig',
    'NPM_CONFIG_USERCONFIG',
    'npm_config_globalconfig',
    'NPM_CONFIG_GLOBALCONFIG',
)
