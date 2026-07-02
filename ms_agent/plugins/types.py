from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PluginFormat(str, Enum):
    MS_AGENT = 'ms-agent'
    CLAUDE = 'claude'
    CODEX = 'codex'
    CURSOR = 'cursor'
    OPENCLAW = 'openclaw'
    HERMES = 'hermes'
    GENERIC = 'generic'
    MIXED = 'mixed'


LOADABLE_CAPABILITIES = frozenset({
    'skills',
    'commands',
    'agents',
    'hooks',
    'mcp',
    'settings',
    'bin',
    'user_config',
})

CAPABILITY_STATUS_KEYS = (
    'skills',
    'commands',
    'agents',
    'hooks',
    'mcp',
    'settings',
    'bin',
    'user_config',
    'assets',
    'apps',
    'rules',
    'lsp',
    'output_styles',
    'themes',
    'monitors',
    'channels',
    'hooks_openclaw_internal',
    'hooks_hermes_python',
)


@dataclass(frozen=True)
class ComponentScan:
    status: str
    count: int = 0
    path: str | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in asdict(self).items()
            if v not in (None, 0) or k in {'status', 'count'}
        }


@dataclass(frozen=True)
class InstallSource:
    type: str = 'local'
    uri: str | None = None
    resolved_sha: str | None = None

    @classmethod
    def from_raw(cls, raw: Any) -> 'InstallSource':
        if isinstance(raw, InstallSource):
            return raw
        if isinstance(raw, dict):
            return cls(
                type=str(raw.get('type', 'local')),
                uri=raw.get('uri'),
                resolved_sha=raw.get('resolved_sha'),
            )
        if isinstance(raw, str):
            return cls(type='local', uri=raw)
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v for k, v in asdict(self).items()
            if v is not None
        }


@dataclass
class PluginRecord:
    id: str
    path: str
    enabled: bool = True
    managed_by: str = 'ms-agent'
    format: str | PluginFormat | None = None
    manifest_path: str | None = None
    source: InstallSource | dict[str, Any] | str | None = None
    installed_at: str | None = None
    scope: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, scope: str | None = None) -> 'PluginRecord':
        return cls(
            id=str(raw.get('id') or raw.get('plugin_id') or raw.get('name')),
            enabled=bool(raw.get('enabled', True)),
            managed_by=str(raw.get('managed_by', 'ms-agent')),
            format=raw.get('format'),
            manifest_path=raw.get('manifest_path'),
            source=InstallSource.from_raw(raw.get('source')),
            path=str(raw.get('path') or ''),
            installed_at=raw.get('installed_at'),
            scope=scope or raw.get('scope'),
        )

    def to_dict(self) -> dict[str, Any]:
        fmt = self.format.value if isinstance(self.format, PluginFormat) else self.format
        source = InstallSource.from_raw(self.source).to_dict()
        data = {
            'id': self.id,
            'enabled': self.enabled,
            'managed_by': self.managed_by,
            'format': fmt,
            'manifest_path': self.manifest_path,
            'source': source,
            'path': self.path,
            'installed_at': self.installed_at,
        }
        return {k: v for k, v in data.items() if v not in (None, {}, '')}


@dataclass(frozen=True)
class CommandDef:
    plugin_id: str
    name: str
    path: str
    description: str | None = None
    argument_hint: str | None = None


@dataclass(frozen=True)
class AgentDef:
    plugin_id: str
    name: str
    path: str
    description: str | None = None
    model: str | None = None
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnsupportedCapability:
    capability: str
    status: str = 'unsupported'
    hint: str | None = None


def component_status_dict(
    components: dict[str, ComponentScan],
) -> dict[str, dict[str, Any]]:
    return {
        key: components.get(key, ComponentScan(status='skipped')).to_dict()
        for key in CAPABILITY_STATUS_KEYS
    }
