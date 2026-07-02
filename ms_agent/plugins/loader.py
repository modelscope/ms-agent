from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ms_agent.hooks.loaders.claude import ClaudeSettingsLoader
from ms_agent.hooks.loaders.hermes import HermesShellLoader
from ms_agent.hooks.registry import HookRegistry
from ms_agent.plugins.manifest import PluginManifest
from ms_agent.plugins.types import AgentDef, CommandDef, UnsupportedCapability
from ms_agent.skill.schema import SkillSchemaParser
from ms_agent.skill.sources import SkillSource, SkillSourceType
from ms_agent.utils import get_logger

logger = get_logger()


@dataclass(frozen=True)
class PluginLoadContext:
    project_path: str
    session_id: str
    enabled_executors: frozenset[str]
    plugin_data_root: Path


@dataclass(frozen=True)
class PluginHookContribution:
    plugin_id: str
    registry: HookRegistry
    plugin_root: Path
    plugin_data_dir: Path


@dataclass
class PluginLoadResult:
    skill_sources: list[SkillSource] = field(default_factory=list)
    hook_registries: list[PluginHookContribution] = field(default_factory=list)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    command_defs: list[CommandDef] = field(default_factory=list)
    agent_defs: list[AgentDef] = field(default_factory=list)
    settings_patch: dict[str, Any] = field(default_factory=dict)
    bin_paths: list[Path] = field(default_factory=list)
    user_config_schema: dict[str, Any] = field(default_factory=dict)
    ui_metadata: dict[str, Any] = field(default_factory=dict)
    unsupported: list[UnsupportedCapability] = field(default_factory=list)

    def merge(self, other: 'PluginLoadResult') -> 'PluginLoadResult':
        self.skill_sources.extend(other.skill_sources)
        self.hook_registries.extend(other.hook_registries)
        for name, server in other.mcp_servers.items():
            candidate = name
            if candidate in self.mcp_servers:
                plugin_id = server.get('plugin_id')
                base = f'plugin.{plugin_id}.{name}' if plugin_id else name
                candidate = _unique_mcp_name(base, set(self.mcp_servers))
            self.mcp_servers[candidate] = server
        self.command_defs.extend(other.command_defs)
        self.agent_defs.extend(other.agent_defs)
        self.settings_patch.update(other.settings_patch)
        self.bin_paths.extend(other.bin_paths)
        self.user_config_schema.update(other.user_config_schema)
        self.ui_metadata.update(other.ui_metadata)
        self.unsupported.extend(other.unsupported)
        return self


class PluginLoader:
    @staticmethod
    def load(manifest: PluginManifest, ctx: PluginLoadContext) -> PluginLoadResult:
        result = PluginLoadResult()
        data_dir = ctx.plugin_data_root / manifest.plugin_id
        data_dir.mkdir(parents=True, exist_ok=True)
        user_config = _load_user_config(data_dir)

        result.skill_sources.extend(_load_skill_sources(manifest))
        result.command_defs.extend(_load_commands(manifest))
        result.skill_sources.extend(
            _command_defs_to_skill_sources(manifest, result.command_defs))
        result.agent_defs.extend(_load_agents(manifest))

        if 'hooks' in manifest.capabilities:
            registry = _load_hook_registry(manifest, ctx, data_dir, user_config)
            if not registry.is_empty:
                registry = registry.with_plugin_source(
                    plugin_id=manifest.plugin_id,
                    plugin_root=str(manifest.root),
                    plugin_data_dir=str(data_dir),
                )
                result.hook_registries.append(
                    PluginHookContribution(
                        plugin_id=manifest.plugin_id,
                        registry=registry,
                        plugin_root=manifest.root,
                        plugin_data_dir=data_dir,
                    ))

        result.mcp_servers.update(_load_mcp_servers(manifest, data_dir, ctx))
        result.settings_patch.update(_load_settings(manifest.root))
        result.bin_paths.extend(_load_bin_paths(manifest.root))
        result.user_config_schema.update((manifest.raw or {}).get('userConfig') or {})
        result.ui_metadata.update(_load_ui_metadata(manifest))
        result.unsupported.extend(_load_unsupported(manifest))
        return result

    @staticmethod
    def load_all(
        manifests: list[PluginManifest],
        ctx: PluginLoadContext,
    ) -> PluginLoadResult:
        result = PluginLoadResult()
        for manifest in sorted(manifests, key=lambda item: item.plugin_id):
            try:
                result.merge(PluginLoader.load(manifest, ctx))
            except Exception as exc:
                logger.warning(
                    'Failed to load plugin %s: %s', manifest.plugin_id, exc)
        return result


def _load_skill_sources(manifest: PluginManifest) -> list[SkillSource]:
    return [
        SkillSource(
            type=SkillSourceType.LOCAL_DIR,
            path=str(path),
            origin='plugin',
            plugin_id=manifest.plugin_id,
            capability='skills',
        )
        for path in manifest.resolve_paths('skills')
    ]


def _command_defs_to_skill_sources(
    manifest: PluginManifest,
    command_defs: list[CommandDef],
) -> list[SkillSource]:
    """Expose plugin commands as SkillCatalog sources (strategy A)."""
    return [
        SkillSource(
            type=SkillSourceType.LOCAL_DIR,
            path=cmd.path,
            origin='plugin',
            plugin_id=manifest.plugin_id,
            capability='commands',
        )
        for cmd in command_defs
        if cmd.plugin_id == manifest.plugin_id
    ]


def _iter_command_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob('*.md'))


def _iter_agent_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob('*.md'))
    for child in sorted(path.iterdir()):
        if not child.is_dir():
            continue
        agent_md = child / 'AGENT.md'
        if agent_md.is_file():
            logger.warning(
                'Deprecated agents/*/AGENT.md layout at %s; prefer agents/*.md',
                agent_md,
            )
            files.append(agent_md)
    return files


def _load_commands(manifest: PluginManifest) -> list[CommandDef]:
    defs: list[CommandDef] = []
    for path in manifest.resolve_paths('commands'):
        for file_path in _iter_command_files(path):
            frontmatter = _read_frontmatter(file_path)
            defs.append(
                CommandDef(
                    plugin_id=manifest.plugin_id,
                    name=frontmatter.get('name') or file_path.stem,
                    path=str(file_path),
                    description=frontmatter.get('description'),
                    argument_hint=frontmatter.get(
                        'argument-hint', frontmatter.get('argument_hint')),
                ))
    return defs


def _load_agents(manifest: PluginManifest) -> list[AgentDef]:
    defs: list[AgentDef] = []
    for path in manifest.resolve_paths('agents'):
        for file_path in _iter_agent_files(path):
            frontmatter = _read_frontmatter(file_path)
            defs.append(
                AgentDef(
                    plugin_id=manifest.plugin_id,
                    name=frontmatter.get('name') or file_path.stem,
                    path=str(file_path),
                    description=frontmatter.get('description'),
                    model=frontmatter.get('model'),
                    tools=_as_tuple(frontmatter.get('tools')),
                    skills=_as_tuple(frontmatter.get('skills')),
                    disallowed_tools=_as_tuple(
                        frontmatter.get('disallowedTools', frontmatter.get(
                            'disallowed_tools'))),
                ))
    return defs


def _load_mcp_servers(
    manifest: PluginManifest,
    data_dir: Path,
    ctx: PluginLoadContext,
) -> dict[str, dict[str, Any]]:
    raw = manifest.raw or {}
    candidates: list[Any] = []
    if isinstance(raw.get('mcpServers'), dict):
        candidates.append(raw['mcpServers'])
    for path in manifest.resolve_paths('mcp'):
        if path.is_file():
            try:
                with open(path, encoding='utf-8') as f:
                    candidates.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue

    servers: dict[str, dict[str, Any]] = {}
    for item in candidates:
        entries = item.get('mcpServers', item) if isinstance(item, dict) else {}
        if not isinstance(entries, dict):
            continue
        for name, server in entries.items():
            if not isinstance(server, dict):
                continue
            server_name = str(name)
            if server_name in servers:
                server_name = _unique_mcp_name(
                    f'plugin.{manifest.plugin_id}.{server_name}',
                    set(servers),
                )
            expanded = _expand_vars(
                copy.deepcopy(server),
                manifest.root,
                data_dir,
                Path(ctx.project_path),
            )
            expanded['source'] = 'plugin'
            expanded['plugin_id'] = manifest.plugin_id
            expanded.setdefault('enabled', True)
            servers[server_name] = expanded
    return servers


def _load_hook_registry(
    manifest: PluginManifest,
    ctx: PluginLoadContext,
    data_dir: Path,
    user_config: dict[str, Any],
) -> HookRegistry:
    registry = HookRegistry(_index={})
    raw_hooks = (manifest.raw or {}).get('hooks')
    if isinstance(raw_hooks, dict):
        try:
            hooks = raw_hooks.get('hooks', raw_hooks)
            registry = registry.merge(
                ClaudeSettingsLoader.parse_hooks(
                    hooks,
                    ctx.project_path,
                    plugin_root=str(manifest.root),
                    plugin_data_dir=str(data_dir),
                    user_config=user_config,
                    enabled_executors=ctx.enabled_executors,
                ))
        except Exception as exc:
            logger.warning(
                'Failed to load inline hooks for plugin %s: %s',
                manifest.plugin_id,
                exc,
            )

    loaded_paths = set()
    for path in manifest.resolve_paths('hooks'):
        loaded_paths.add(path.resolve())
        try:
            if path.suffix in {'.yaml', '.yml'}:
                loaded = HermesShellLoader.load_file(
                    path,
                    ctx.project_path,
                    plugin_root=str(manifest.root),
                    plugin_data_dir=str(data_dir),
                    user_config=user_config,
                    enabled_executors=ctx.enabled_executors,
                )
            else:
                loaded = ClaudeSettingsLoader.parse_hooks_file(
                    path,
                    plugin_root=str(manifest.root),
                    plugin_data_dir=str(data_dir),
                    user_config=user_config,
                    project_path=ctx.project_path,
                    enabled_executors=ctx.enabled_executors,
                )
            registry = registry.merge(loaded)
        except Exception as exc:
            logger.warning(
                'Failed to load hooks for plugin %s from %s: %s',
                manifest.plugin_id,
                path,
                exc,
            )

    for path in (
        manifest.root / 'hooks' / 'hermes.yaml',
        manifest.root / 'hooks' / 'config.yaml',
    ):
        if path.resolve() in loaded_paths:
            continue
        if path.is_file():
            try:
                registry = registry.merge(
                    HermesShellLoader.load_file(
                        path,
                        ctx.project_path,
                        plugin_root=str(manifest.root),
                        plugin_data_dir=str(data_dir),
                        user_config=user_config,
                        enabled_executors=ctx.enabled_executors,
                    ))
            except Exception as exc:
                logger.warning(
                    'Failed to load Hermes hooks for plugin %s from %s: %s',
                    manifest.plugin_id,
                    path,
                    exc,
                )
    return registry


def _unique_mcp_name(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 1
    while candidate in used:
        candidate = f'{base}.{suffix}'
        suffix += 1
    return candidate


def _load_settings(root: Path) -> dict[str, Any]:
    path = root / 'settings.json'
    if not path.is_file():
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    allowed = {'agent', 'subagentStatusLine'}
    return {key: value for key, value in data.items() if key in allowed}


def _load_bin_paths(root: Path) -> list[Path]:
    path = root / 'bin'
    if not path.is_dir():
        return []
    return [path]


def _load_ui_metadata(manifest: PluginManifest) -> dict[str, Any]:
    raw = manifest.raw or {}
    metadata: dict[str, Any] = {}
    for key in ('author', 'homepage', 'repository', 'license', 'keywords',
                'displayName', 'interface'):
        if key in raw:
            metadata[key] = raw[key]
    assets = manifest.root / 'assets'
    if assets.is_dir():
        metadata['assets_path'] = str(assets)
    return metadata


def _load_unsupported(manifest: PluginManifest) -> list[UnsupportedCapability]:
    unsupported: list[UnsupportedCapability] = []
    for capability, scan in manifest.components.items():
        if scan.status in {'unsupported', 'detect_only'}:
            unsupported.append(
                UnsupportedCapability(
                    capability=capability,
                    status=scan.status,
                    hint=scan.hint,
                ))
    return unsupported


def _read_frontmatter(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        return {}
    return SkillSchemaParser.parse_yaml_frontmatter(content) or {}


def _load_user_config(data_dir: Path) -> dict[str, Any]:
    path = data_dir / 'config.json'
    if not path.is_file():
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(',') if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _expand_vars(
    value: Any,
    plugin_root: Path,
    plugin_data_dir: Path,
    project_path: Path,
    user_config: dict[str, Any] | None = None,
) -> Any:
    if user_config is None:
        user_config = _load_user_config(plugin_data_dir)
    if isinstance(value, str):
        expanded = (
            value
            .replace('${MS_AGENT_PLUGIN_ROOT}', str(plugin_root))
            .replace('${CLAUDE_PLUGIN_ROOT}', str(plugin_root))
            .replace('${MS_AGENT_PLUGIN_DATA}', str(plugin_data_dir))
            .replace('${CLAUDE_PLUGIN_DATA}', str(plugin_data_dir))
            .replace('${MS_AGENT_PROJECT_DIR}', str(project_path))
            .replace('${CLAUDE_PROJECT_DIR}', str(project_path))
        )
        for key, item in user_config.items():
            expanded = expanded.replace(f'${{user_config.{key}}}', str(item))
            expanded = expanded.replace(
                f'${{CLAUDE_PLUGIN_OPTION_{key.upper()}}}', str(item))
        return expanded
    if isinstance(value, list):
        return [
            _expand_vars(
                item, plugin_root, plugin_data_dir, project_path, user_config)
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _expand_vars(
                item, plugin_root, plugin_data_dir, project_path, user_config)
            for key, item in value.items()
        }
    return value
