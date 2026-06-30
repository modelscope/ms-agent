import json
import tarfile

import pytest

from ms_agent.hooks.executors.command import HookExecutionContext, build_hook_env
from ms_agent.plugins.agents import AgentDelegate, PluginAgentRegistry
from ms_agent.plugins.dependencies import PluginDependencyError, version_satisfies
from ms_agent.plugins.installer import (
    PluginInstaller,
    normalize_install_source,
    resolve_ms_agent_uri,
)
from ms_agent.plugins.loader import PluginLoadContext, PluginLoader
from ms_agent.plugins.manifest import PluginManifest
from ms_agent.plugins.registry import PluginRegistry
from ms_agent.plugins.runtime import PluginRuntime
from ms_agent.plugins.types import AgentDef
from ms_agent.plugins.user_config import save_user_config, validate_values
from ms_agent.skill.catalog import SkillCatalog
from ms_agent.skill.sources import SkillSource, SkillSourceType


def _basic_plugin(root, *, user_config=None, dependencies=None):
    (root / '.claude-plugin').mkdir(parents=True)
    manifest = {
        'name': 'p1-demo',
        'version': '1.0.0',
    }
    if user_config:
        manifest['userConfig'] = user_config
    if dependencies:
        manifest['dependencies'] = dependencies
    (root / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps(manifest),
        encoding='utf-8',
    )
    skill = root / 'skills' / 'writer'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text(
        '---\nname: Writer\ndescription: Write better text.\n---\n',
        encoding='utf-8',
    )


def test_ms_agent_uri_resolves_inner_source():
    from urllib.parse import quote
    inner = 'github://anthropics/claude-plugins-official@main#plugins/hookify'
    uri = f'ms-agent://plugin/install?source={quote(inner, safe="")}'
    assert resolve_ms_agent_uri(uri) == inner
    assert normalize_install_source(uri) == inner


def test_tarball_install(tmp_path):
    source = tmp_path / 'source-plugin'
    _basic_plugin(source)
    archive = tmp_path / 'plugin.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(source, arcname='p1-demo')

    global_dir = tmp_path / '.ms_agent'
    from ms_agent.plugins.config_manager import PluginConfigManager
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    manifest = installer.install(str(archive), scope='global')
    assert manifest.plugin_id == 'p1-demo'


def test_dependencies_install_order(tmp_path):
    base = tmp_path / 'base-plugin'
    child = tmp_path / 'child-plugin'
    _basic_plugin(base)
    (base / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({'name': 'base-plugin', 'version': '1.0.0'}),
        encoding='utf-8',
    )
    _basic_plugin(child)
    (child / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({
            'name': 'child-plugin',
            'version': '1.0.0',
            'dependencies': [{
                'name': 'base-plugin',
                'version': '~1.0.0',
                'source': str(base),
            }],
        }),
        encoding='utf-8',
    )

    global_dir = tmp_path / '.ms_agent'
    from ms_agent.plugins.config_manager import PluginConfigManager
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    installer.install(str(child), scope='global')
    assert manager.get('base-plugin', scope='global') is not None
    assert manager.get('child-plugin', scope='global') is not None


def test_missing_dependency_without_source_raises(tmp_path):
    root = tmp_path / 'needs-dep'
    _basic_plugin(root)
    (root / '.claude-plugin' / 'plugin.json').write_text(
        json.dumps({
            'name': 'needs-dep',
            'version': '1.0.0',
            'dependencies': [{'name': 'missing-plugin', 'version': '1.0.0'}],
        }),
        encoding='utf-8',
    )
    global_dir = tmp_path / '.ms_agent'
    from ms_agent.plugins.config_manager import PluginConfigManager
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    with pytest.raises(PluginDependencyError):
        installer.install(str(root), scope='global')


def test_version_satisfies_tilde():
    assert version_satisfies('1.0.5', '~1.0.0')
    assert not version_satisfies('2.0.0', '~1.0.0')


def test_version_satisfies_v_prefix():
    assert version_satisfies('v1.0.5', '~v1.0.0')
    assert version_satisfies('V1.0.5', 'v1.0.5')
    assert not version_satisfies('v2.0.0', '~v1.0.0')


def test_commands_merge_into_skill_catalog(tmp_path):
    root = tmp_path / 'cmd-plugin'
    _basic_plugin(root)
    commands = root / 'commands'
    commands.mkdir()
    (commands / 'deploy.md').write_text(
        '---\nname: deploy\ndescription: Deploy the app.\n---\nRun deploy.',
        encoding='utf-8',
    )
    manifest = PluginManifest.parse(root)
    result = PluginLoader.load(
        manifest,
        PluginLoadContext(
            project_path=str(tmp_path),
            session_id='s1',
            enabled_executors=frozenset({'command'}),
            plugin_data_root=tmp_path / 'data',
        ),
    )
    command_sources = [
        source for source in result.skill_sources
        if source.capability == 'commands'
    ]
    assert len(command_sources) == 1
    catalog = SkillCatalog()
    catalog.load_from_sources(command_sources)
    assert 'p1-demo:deploy' in catalog.get_enabled_skills()


def test_agent_md_subdirectory(tmp_path):
    root = tmp_path / 'agent-plugin'
    _basic_plugin(root)
    agent_dir = root / 'agents' / 'reviewer'
    agent_dir.mkdir(parents=True)
    (agent_dir / 'AGENT.md').write_text(
        '---\nname: reviewer\ndescription: Review code.\n---\nYou review.',
        encoding='utf-8',
    )
    manifest = PluginManifest.parse(root)
    result = PluginLoader.load(
        manifest,
        PluginLoadContext(
            project_path=str(tmp_path),
            session_id='s1',
            enabled_executors=frozenset({'command'}),
            plugin_data_root=tmp_path / 'data',
        ),
    )
    assert any(agent.name == 'reviewer' for agent in result.agent_defs)


def test_build_hook_env_includes_session_id():
    env = build_hook_env(HookExecutionContext(
        session_id='session-123',
        project_path='/tmp/project',
        plugin_root='/tmp/plugin',
        plugin_data_dir='/tmp/data',
    ))
    assert env['MS_AGENT_SESSION_ID'] == 'session-123'


def test_plugin_registry_managed_paths(tmp_path):
    global_dir = tmp_path / '.ms_agent'
    from ms_agent.plugins.config_manager import PluginConfigManager
    from ms_agent.plugins.installer import PluginInstaller
    source = tmp_path / 'source-plugin'
    _basic_plugin(source)
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    installer.install(str(source), scope='global')
    registry = PluginRegistry(manager)
    assert 'p1-demo' in registry.managed_plugin_ids()


def test_resolve_task_entry_maps_builtin_single_agent():
    registry = PluginAgentRegistry()
    registry.rebuild([
        AgentDef(
            plugin_id='hookify',
            name='conversation-analyzer',
            path='/tmp/agents/conversation-analyzer.md',
            description='Analyze conversation',
        ),
    ])
    entry = AgentDelegate.resolve_task_entry(
        registry,
        {'subagent_type': 'general-purpose', 'prompt': 'hi'},
    )
    assert entry is not None
    assert entry.defn.name == 'conversation-analyzer'


def test_user_config_save_and_validate(tmp_path):
    schema = {
        'mode': {'type': 'string', 'title': 'Mode'},
        'strict': {'type': 'boolean', 'title': 'Strict'},
    }
    errors = validate_values(schema, {'mode': 'safe', 'strict': True})
    assert errors == []
    saved = save_user_config(tmp_path / 'data', schema, {'mode': 'safe', 'strict': True})
    assert saved['mode'] == 'safe'


def test_example_plugin_mcp_fixture(tmp_path):
    root = tmp_path / 'example-plugin'
    _basic_plugin(root)
    (root / '.mcp.json').write_text(
        json.dumps({
            'mcpServers': {
                'example': {
                    'type': 'http',
                    'url': 'http://127.0.0.1:9999/mcp',
                },
            },
        }),
        encoding='utf-8',
    )
    (root / 'commands').mkdir()
    (root / 'commands' / 'hello.md').write_text(
        '---\nname: hello\ndescription: Say hello.\n---\nHello.',
        encoding='utf-8',
    )
    manifest = PluginManifest.parse(root)
    result = PluginLoader.load(
        manifest,
        PluginLoadContext(
            project_path=str(tmp_path),
            session_id='s1',
            enabled_executors=frozenset({'command'}),
            plugin_data_root=tmp_path / 'data',
        ),
    )
    assert 'example' in result.mcp_servers
    assert result.mcp_servers['example']['source'] == 'plugin'


def test_runtime_user_config_roundtrip(tmp_path):
    root = tmp_path / 'cfg-plugin'
    _basic_plugin(
        root,
        user_config={'mode': {'type': 'string', 'title': 'Mode'}},
    )
    global_dir = tmp_path / '.ms_agent'
    from ms_agent.plugins.config_manager import PluginConfigManager
    from ms_agent.plugins.installer import PluginInstaller
    manager = PluginConfigManager(global_dir=global_dir)
    installer = PluginInstaller(config_manager=manager, global_root=global_dir)
    installer.install(str(root), scope='global')
    runtime = PluginRuntime(config_manager=manager, global_root=global_dir)
    runtime.start_sync(str(tmp_path), 'test')
    saved = runtime.set_user_config('p1-demo', {'mode': 'strict'})
    assert saved['values']['mode'] == 'strict'
    loaded = runtime.get_user_config('p1-demo')
    assert loaded['values']['mode'] == 'strict'
