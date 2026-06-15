"""Native YAML/JSON hook loaders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ms_agent.hooks.registry import HookRegistry


class NativeYamlLoader:
    @staticmethod
    def load_file(
        path: Path | str,
        *,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        hooks = data.get('hooks', data)
        if not isinstance(hooks, dict):
            return HookRegistry(_index={})
        return HookRegistry.from_dict(
            hooks,
            enabled_executors=enabled_executors,
            source=str(path),
        )


class NativeJsonLoader:
    @staticmethod
    def load_file(
        path: Path | str,
        *,
        enabled_executors: frozenset[str] = frozenset({'command'}),
    ) -> HookRegistry:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        hooks = data.get('hooks', data)
        if not isinstance(hooks, dict):
            return HookRegistry(_index={})
        return HookRegistry.from_dict(
            hooks,
            enabled_executors=enabled_executors,
            source=str(path),
        )
