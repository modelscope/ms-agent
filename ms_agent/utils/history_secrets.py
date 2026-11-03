# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keep API keys and MCP credentials out of the on-disk history yaml.

The yaml under ``<project>/.ms_agent/memory/`` is a turn cache, not the
credential store. Keys stay in ``~/.ms_agent/settings.json`` and MCP headers
stay in ``mcp.json``. A legacy ``read_history`` that installs the yaml as the
live config fills those values back in from those files.
"""
from __future__ import annotations

from typing import Optional


def blank_config_secrets(node) -> None:
    """Blank secret values in a plain config tree. Never writes ``***``."""
    from ms_agent.agent_hub._workspace import (
        SECRET_BAG_KEYS,
        is_secret_key,
        scrub_url_secrets,
    )
    from ms_agent.command.usage import contains_secret

    if isinstance(node, dict):
        for key, val in list(node.items()):
            name = str(key)
            if name in SECRET_BAG_KEYS and isinstance(val, dict):
                node[key] = {
                    inner: ('' if _bag_value_is_secret(inner, inner_val,
                                                       contains_secret,
                                                       is_secret_key)
                            else inner_val)
                    for inner, inner_val in val.items()
                }
                continue
            if is_secret_key(name) and not isinstance(val, (dict, list)):
                if val not in (None, ''):
                    node[key] = ''
                continue
            if isinstance(val, str):
                node[key] = _blank_secret_text(
                    val, contains_secret, scrub_url_secrets)
            else:
                blank_config_secrets(val)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, str):
                node[index] = _blank_secret_text(
                    item, contains_secret, scrub_url_secrets)
            else:
                blank_config_secrets(item)


def config_for_history_disk(config):
    """Copy ``config`` with secrets removed. The caller's object is unchanged."""
    from omegaconf import OmegaConf

    try:
        data = OmegaConf.to_container(config, resolve=False)
    except Exception:
        return config
    if not isinstance(data, dict):
        return config
    blank_config_secrets(data)
    try:
        return OmegaConf.create(data)
    except Exception:
        return config


def refill_history_config(config, work_dir: Optional[str]) -> None:
    """Put keys and MCP headers back after a stripped yaml is loaded.

    ``overwrite`` so an emptied ``api_key`` does not hide the value in
    settings.json. MCP is replaced from mcp.json so a blanked
    ``Authorization`` does not stick.
    """
    if config is None:
        return
    try:
        from ms_agent.tui.app import TuiApp
        TuiApp._apply_provider_credentials(config, overwrite=True)
    except Exception:
        pass
    try:
        from omegaconf import OmegaConf

        from ms_agent.config.resolver import ConfigResolver
        from ms_agent.project.paths import global_home

        fresh = OmegaConf.create({})
        ConfigResolver(
            global_home(), project_root=work_dir)._merge_mcp(fresh, work_dir)
        merged = OmegaConf.select(fresh, '_merged_mcp', default=None)
        if merged:
            OmegaConf.update(
                config,
                '_merged_mcp',
                OmegaConf.to_container(merged, resolve=False),
                merge=False,
            )
    except Exception:
        pass


def _bag_value_is_secret(name, value, contains_secret, is_secret_key) -> bool:
    if value in (None, ''):
        return False
    if is_secret_key(str(name)):
        return True
    return contains_secret(str(value))


def _blank_secret_text(value, contains_secret, scrub_url_secrets) -> str:
    if not value:
        return value
    cleaned = scrub_url_secrets(value)
    if cleaned != value:
        return cleaned
    if contains_secret(value) and ' ' not in value and '\n' not in value:
        return ''
    return value
