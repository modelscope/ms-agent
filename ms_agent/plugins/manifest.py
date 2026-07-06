from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ms_agent.plugins.types import (
    LOADABLE_CAPABILITIES,
    ComponentScan,
    InstallSource,
    PluginFormat,
    PluginRecord,
)

_PLUGIN_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
_SEMVER_RE = re.compile(r'^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$')

_MANIFEST_CANDIDATES: tuple[tuple[str, PluginFormat], ...] = (
    ('.ms-agent-plugin/plugin.json', PluginFormat.MS_AGENT),
    ('plugin.json', PluginFormat.GENERIC),
    ('.claude-plugin/plugin.json', PluginFormat.CLAUDE),
    ('.codex-plugin/plugin.json', PluginFormat.CODEX),
    ('.cursor-plugin/plugin.json', PluginFormat.CURSOR),
    ('openclaw.plugin.json', PluginFormat.OPENCLAW),
)


class PluginError(ValueError):
    """Base class for plugin parsing and validation errors."""


class AmbiguousPluginManifest(PluginError):
    """Raised when multiple non-native manifest formats are present."""


class EmptyPluginError(PluginError):
    """Raised when a plugin contains no loadable component."""


class InvalidPluginManifest(PluginError):
    """Raised when plugin.json is invalid or violates required fields."""


@dataclass(frozen=True)
class ManifestCandidate:
    path: Path
    format: PluginFormat
    raw: dict[str, Any]

    @property
    def rel_path(self) -> str:
        return self.path.as_posix()


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str
    root: Path
    format: PluginFormat
    manifest_path: str
    capabilities: frozenset[str]
    components: dict[str, ComponentScan]
    source: InstallSource
    installed_at: str | None = None
    enabled: bool = True
    raw: dict[str, Any] | None = None

    @classmethod
    def parse(
        cls,
        root: str | Path,
        *,
        record: PluginRecord | dict[str, Any] | None = None,
        format_hint: str | PluginFormat | None = None,
    ) -> 'PluginManifest':
        root_path = Path(root).expanduser().resolve()
        plugin_record: PluginRecord | None = None
        if record is not None:
            plugin_record = (
                record if isinstance(record, PluginRecord)
                else PluginRecord.from_dict(record)
            )

        if plugin_record and plugin_record.manifest_path:
            manifest_path = _locked_manifest_path(
                root_path,
                plugin_record.manifest_path,
            )
            raw = _read_manifest(root_path / manifest_path)
            fmt = _coerce_format(plugin_record.format) or _format_for_path(
                manifest_path.as_posix(), raw)
            candidate = ManifestCandidate(manifest_path, fmt, raw)
        else:
            candidate = detect_manifest(root_path, format_hint=format_hint)

        raw = candidate.raw
        name = str(raw.get('name') or '').strip()
        if not name:
            raise InvalidPluginManifest('Plugin manifest requires "name"')
        plugin_id = normalize_plugin_id(name)
        if not _PLUGIN_NAME_RE.match(plugin_id):
            raise InvalidPluginManifest(f'Invalid plugin name: {name}')

        version = str(raw.get('version') or 'latest')
        if version != 'latest' and not _SEMVER_RE.match(version):
            raise InvalidPluginManifest(f'Invalid plugin version: {version}')

        components = scan_components(root_path, raw)
        capabilities = frozenset(
            key for key, scan in components.items()
            if key in LOADABLE_CAPABILITIES and scan.status == 'ready'
        )
        if not capabilities:
            raise EmptyPluginError(f'Plugin has no loadable components: {root_path}')

        enabled = (
            plugin_record.enabled
            if plugin_record
            else bool(raw.get('defaultEnabled', True))
        )
        return cls(
            plugin_id=plugin_id,
            name=name,
            version=version,
            description=str(raw.get('description') or ''),
            root=root_path,
            format=candidate.format,
            manifest_path=candidate.rel_path,
            capabilities=capabilities,
            components=components,
            source=InstallSource.from_raw(
                plugin_record.source if plugin_record else raw.get('source')),
            installed_at=plugin_record.installed_at if plugin_record else None,
            enabled=enabled,
            raw=raw,
        )

    def resolve_paths(self, kind: str) -> list[Path]:
        raw = self.raw or {}
        if kind == 'skills':
            paths = _paths_from_manifest_field(self.root, raw.get('skills'))
            if not paths and (self.root / 'skills').is_dir():
                paths.append(self.root / 'skills')
            if (self.root / 'SKILL.md').is_file():
                paths.append(self.root)
            return _dedupe_paths(paths)
        if kind == 'commands':
            paths = _paths_from_manifest_field(self.root, raw.get('commands'))
            if not paths and (self.root / 'commands').is_dir():
                paths.append(self.root / 'commands')
            return _dedupe_paths(paths)
        if kind == 'agents':
            paths = _paths_from_manifest_field(self.root, raw.get('agents'))
            if not paths and (self.root / 'agents').is_dir():
                paths.append(self.root / 'agents')
            return _dedupe_paths(paths)
        if kind == 'hooks':
            paths = _paths_from_manifest_field(self.root, raw.get('hooks'))
            hooks_json = self.root / 'hooks' / 'hooks.json'
            if hooks_json.is_file():
                paths.append(hooks_json)
            return _dedupe_paths(paths)
        if kind == 'mcp':
            paths = _paths_from_manifest_field(self.root, raw.get('mcpServers'))
            for default_path in (
                self.root / '.mcp.json',
                self.root / 'tools' / 'mcp.json',
                self.root / 'openclaw.json',
            ):
                if default_path.is_file():
                    paths.append(default_path)
            return _dedupe_paths(paths)
        return []


def normalize_plugin_id(name: str) -> str:
    return name.strip().lower().replace('/', '-')


def detect_manifest(
    root: str | Path,
    *,
    format_hint: str | PluginFormat | None = None,
) -> ManifestCandidate:
    root_path = Path(root).expanduser().resolve()
    candidates = _scan_manifest_candidates(root_path)
    if not candidates:
        synthetic = _detect_manifestless_bundle(root_path)
        if synthetic is not None:
            return synthetic
        raise InvalidPluginManifest(f'No plugin manifest found in {root_path}')

    if format_hint:
        wanted = _coerce_format(format_hint)
        for candidate in candidates:
            if candidate.format == wanted:
                return candidate
        raise InvalidPluginManifest(
            f'No {wanted.value if wanted else format_hint} manifest found')

    if len(candidates) == 1:
        return candidates[0]

    native = _pick_ms_agent_native(candidates)
    if native is not None:
        return native

    raise AmbiguousPluginManifest(
        'Multiple plugin manifests found: '
        + ', '.join(c.rel_path for c in candidates))


def scan_components(
    root: str | Path,
    manifest: dict[str, Any] | None = None,
) -> dict[str, ComponentScan]:
    root_path = Path(root)
    manifest = manifest or {}
    components: dict[str, ComponentScan] = {}

    skill_count = _count_skill_dirs(root_path / 'skills')
    if (root_path / 'SKILL.md').is_file():
        skill_count += 1
    if manifest.get('skills') and skill_count == 0:
        skill_count = _count_paths(root_path, manifest['skills'], 'SKILL.md')
    components['skills'] = _scan('ready', skill_count, root_path / 'skills')

    command_count = _count_markdown_files(root_path / 'commands')
    if manifest.get('commands') and command_count == 0:
        command_count = _count_paths(root_path, manifest['commands'], '*.md')
    components['commands'] = _scan('ready', command_count, root_path / 'commands')

    agent_count = _count_markdown_files(root_path / 'agents')
    agent_count += _count_agent_md_subdirs(root_path / 'agents')
    if manifest.get('agents') and agent_count == 0:
        agent_count = _count_paths(root_path, manifest['agents'], '*.md')
    components['agents'] = _scan('ready', agent_count, root_path / 'agents')

    hook_count = 0
    if (root_path / 'hooks' / 'hooks.json').is_file():
        hook_count += 1
    if (root_path / 'hooks' / 'hermes.yaml').is_file():
        hook_count += 1
    if (root_path / 'hooks' / 'config.yaml').is_file():
        hook_count += 1
    hooks_field = manifest.get('hooks')
    if hooks_field:
        if isinstance(hooks_field, dict):
            hook_count += 1
        else:
            hook_count += sum(
                1 for path in _paths_from_manifest_field(root_path, hooks_field)
                if path.exists()
            )
    components['hooks'] = _scan('ready', hook_count, root_path / 'hooks')

    mcp_count = 0
    if (root_path / '.mcp.json').is_file():
        mcp_count += 1
    if (root_path / 'tools' / 'mcp.json').is_file():
        mcp_count += 1
    if (root_path / 'openclaw.json').is_file():
        mcp_count += 1
    mcp_field = manifest.get('mcpServers')
    if mcp_field:
        if isinstance(mcp_field, dict):
            mcp_count += 1
        else:
            mcp_count += sum(
                1 for path in _paths_from_manifest_field(root_path, mcp_field)
                if path.exists()
            )
    components['mcp'] = _scan('ready', mcp_count, root_path / '.mcp.json')

    settings_count = 1 if _non_empty_json(root_path / 'settings.json') else 0
    components['settings'] = _scan(
        'ready', settings_count, root_path / 'settings.json')

    bin_count = _count_executable_files(root_path / 'bin')
    components['bin'] = _scan('ready', bin_count, root_path / 'bin')

    user_config_count = 1 if manifest.get('userConfig') else 0
    components['user_config'] = _scan('ready', user_config_count, None)

    components['assets'] = _detect_only(root_path / 'assets')
    components['apps'] = _detect_only(root_path / '.app.json')
    components['rules'] = _detect_only(root_path / 'rules')
    components['lsp'] = _detect_only(root_path / '.lsp.json')
    components['output_styles'] = _detect_only(root_path / 'output-styles')
    components['themes'] = _detect_only(root_path / 'themes')
    components['monitors'] = _detect_only(root_path / 'monitors')
    components['channels'] = _scan(
        'detect_only' if manifest.get('channels') else 'skipped',
        1 if manifest.get('channels') else 0,
        None,
    )
    components['hooks_openclaw_internal'] = _scan(
        'unsupported' if list(root_path.glob('hooks/*/HOOK.md')) else 'skipped',
        len(list(root_path.glob('hooks/*/HOOK.md'))),
        root_path / 'hooks',
        hint='OpenClaw in-process hooks are detect-only.',
    )
    components['hooks_hermes_python'] = _scan('skipped', 0, None)
    return components


def _scan_manifest_candidates(root: Path) -> list[ManifestCandidate]:
    candidates: list[ManifestCandidate] = []
    for rel, default_format in _MANIFEST_CANDIDATES:
        path = root / rel
        if path.is_file():
            raw = _read_manifest(path)
            fmt = _format_for_path(rel, raw, default_format)
            candidates.append(ManifestCandidate(Path(rel), fmt, raw))
    return candidates


def _detect_manifestless_bundle(root: Path) -> ManifestCandidate | None:
    package_json = root / 'package.json'
    if package_json.is_file():
        try:
            raw_package = _read_manifest(package_json)
        except InvalidPluginManifest:
            raw_package = {}
        openclaw_cfg = raw_package.get('openclaw') or raw_package.get(
            'openclaw.hooks')
        if openclaw_cfg or list(root.glob('hooks/*/HOOK.md')):
            raw = {
                'name': raw_package.get('name') or root.name,
                'version': raw_package.get('version', 'latest'),
                'description': raw_package.get('description', ''),
            }
            return ManifestCandidate(Path('package.json'), PluginFormat.OPENCLAW, raw)

    for rel in ('hooks/hermes.yaml', 'hooks/config.yaml'):
        if (root / rel).is_file():
            raw = {
                'name': root.name,
                'version': 'latest',
                'description': 'Hermes shell hook bundle',
            }
            return ManifestCandidate(Path(rel), PluginFormat.HERMES, raw)
    return None


def _pick_ms_agent_native(
    candidates: list[ManifestCandidate],
) -> ManifestCandidate | None:
    for candidate in candidates:
        if candidate.format == PluginFormat.MS_AGENT:
            return candidate
    return None


def _format_for_path(
    rel_path: str,
    raw: dict[str, Any],
    default: PluginFormat | None = None,
) -> PluginFormat:
    if rel_path == 'plugin.json' and raw.get('ms_agent'):
        return PluginFormat.MS_AGENT
    if default and default != PluginFormat.GENERIC:
        return default
    return default or PluginFormat.GENERIC


def _coerce_format(value: str | PluginFormat | None) -> PluginFormat | None:
    if value is None:
        return None
    if isinstance(value, PluginFormat):
        return value
    return PluginFormat(str(value))


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidPluginManifest(f'Invalid plugin manifest: {path}') from exc
    if not isinstance(data, dict):
        raise InvalidPluginManifest(f'Plugin manifest must be an object: {path}')
    return data


def _locked_manifest_path(root: Path, value: str) -> Path:
    raw_path = Path(value).expanduser()
    resolved = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        return resolved.resolve().relative_to(root)
    except ValueError as exc:
        raise InvalidPluginManifest(
            f'Locked manifest path escapes plugin root: {value}') from exc


def _paths_from_manifest_field(root: Path, raw: Any) -> list[Path]:
    if not raw or isinstance(raw, dict):
        return []
    values = raw if isinstance(raw, list) else [raw]
    paths: list[Path] = []
    for value in values:
        if not isinstance(value, str):
            continue
        paths.append(_resolve_plugin_child(root, value))
    return paths


def _resolve_plugin_child(root: Path, value: str) -> Path:
    root_resolved = root.expanduser().resolve()
    raw_path = Path(value).expanduser()
    path = raw_path if raw_path.is_absolute() else root_resolved / raw_path
    resolved = path.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise InvalidPluginManifest(
            f'Plugin component path escapes plugin root: {value}') from exc
    return resolved


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen and path.exists():
            seen.add(key)
            result.append(path)
    return result


def _scan(
    ready_status: str,
    count: int,
    path: Path | None,
    hint: str | None = None,
) -> ComponentScan:
    if count <= 0:
        return ComponentScan(status='skipped', count=0)
    return ComponentScan(
        status=ready_status,
        count=count,
        path=str(path) if path else None,
        hint=hint,
    )


def _detect_only(path: Path) -> ComponentScan:
    if path.is_dir():
        count = sum(1 for _ in path.iterdir())
        return ComponentScan(status='detect_only', count=count, path=str(path))
    if path.is_file():
        return ComponentScan(status='detect_only', count=1, path=str(path))
    return ComponentScan(status='skipped', count=0)


def _count_skill_dirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if (child / 'SKILL.md').is_file())


def _count_markdown_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.glob('*.md') if child.is_file())


def _count_agent_md_subdirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(
        1 for child in path.iterdir()
        if child.is_dir() and (child / 'AGENT.md').is_file()
    )


def _count_executable_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_file())


def _count_paths(root: Path, raw: Any, marker: str) -> int:
    count = 0
    for path in _paths_from_manifest_field(root, raw):
        if path.is_file():
            count += 1
        elif path.is_dir() and marker == 'SKILL.md':
            count += _count_skill_dirs(path)
        elif path.is_dir():
            count += len(list(path.glob(marker)))
    return count


def _non_empty_json(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return bool(data)
    except (OSError, json.JSONDecodeError):
        return False
