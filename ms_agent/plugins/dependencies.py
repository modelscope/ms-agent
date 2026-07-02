"""Plugin dependency parsing and version constraint checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ms_agent.plugins.manifest import normalize_plugin_id

_VERSION_RE = re.compile(r'^(\d+)\.(\d+)\.(\d+)')


@dataclass(frozen=True)
class PluginDependency:
    name: str
    version: str | None = None
    source: str | None = None

    @property
    def plugin_id(self) -> str:
        return normalize_plugin_id(self.name)


class PluginDependencyError(ValueError):
    """Raised when a plugin dependency cannot be satisfied."""


def parse_dependencies(raw: dict[str, Any] | None) -> list[PluginDependency]:
    if not raw:
        return []
    items = raw.get('dependencies')
    if not items:
        return []
    if not isinstance(items, list):
        raise PluginDependencyError('manifest dependencies must be an array')
    deps: list[PluginDependency] = []
    for item in items:
        if isinstance(item, str):
            deps.append(PluginDependency(name=item))
            continue
        if not isinstance(item, dict):
            raise PluginDependencyError('dependency entries must be objects or strings')
        name = item.get('name') or item.get('id')
        if not name:
            raise PluginDependencyError('dependency entry requires name')
        deps.append(
            PluginDependency(
                name=str(name),
                version=item.get('version'),
                source=item.get('source') or item.get('uri'),
            ))
    return deps


def version_satisfies(installed: str, constraint: str | None) -> bool:
    if not constraint or constraint in {'*', 'latest'}:
        return True
    if installed in {'latest', ''}:
        return True
    installed_parts = _parse_version(installed)
    if installed_parts is None:
        return True
    constraint = constraint.strip()
    if constraint.startswith('~'):
        base = _parse_version(constraint[1:])
        if base is None:
            return True
        return installed_parts[:2] == base[:2] and installed_parts >= base
    if constraint.startswith('^'):
        base = _parse_version(constraint[1:])
        if base is None:
            return True
        return installed_parts >= base and installed_parts[0] == base[0]
    if constraint.startswith('>='):
        base = _parse_version(constraint[2:])
        return base is None or installed_parts >= base
    exact = _parse_version(constraint)
    if exact is None:
        return True
    return installed_parts == exact


def _parse_version(value: str) -> tuple[int, int, int] | None:
    val = str(value).strip().lstrip('vV')
    match = _VERSION_RE.match(val)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))
