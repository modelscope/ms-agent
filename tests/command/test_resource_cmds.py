"""TUI /mcp and /skills write the same manager files WebUI uses."""
from dataclasses import dataclass, field

import pytest
from omegaconf import OmegaConf

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResultType
from ms_agent.config import MCPConfigManager
from ms_agent.config.skills_manager import SkillsConfigManager


def make_router():
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def make_ctx(text, runtime=None, extra=None):
    router = make_router()
    cmd, args = CommandRouter.parse_input(text)
    payload = {'router': router}
    if extra:
        payload.update(extra)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='cli',
        runtime=runtime,
        extra=payload,
    )


@dataclass
class MockRuntime:
    config: object = field(default_factory=lambda: OmegaConf.create({}))
    tool_manager: object = None
    _skill_runtime: object = None


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    return home


class TestMcpCommand:
    @pytest.mark.asyncio
    async def test_help(self):
        result = await make_router().dispatch(make_ctx('/mcp'))
        assert result.type == CommandResultType.MESSAGE
        assert result.content.startswith('No MCP servers.')
        assert '/mcp list' in result.content

    @pytest.mark.asyncio
    async def test_help_flag_is_usage_only(self):
        result = await make_router().dispatch(make_ctx('/mcp help'))
        assert result.content.startswith('usage:')
        assert 'No MCP servers' not in result.content

    @pytest.mark.asyncio
    async def test_missing_args_is_focused(self):
        result = await make_router().dispatch(
            make_ctx('/mcp json', MockRuntime()))
        assert 'Need: /mcp json <file.json>' in result.content
        assert 'Got:  /mcp json' in result.content
        assert '/mcp add' not in result.content

    @pytest.mark.asyncio
    async def test_add_list_disable_global(self, isolate_home):
        runtime = MockRuntime()
        router = make_router()
        added = await router.dispatch(
            make_ctx(
                '/mcp add docs global url=https://example/mcp',
                runtime=runtime))
        assert 'Added docs' in added.content
        assert 'Settings' not in added.content

        listed = await router.dispatch(make_ctx('/mcp list global', runtime))
        assert 'docs' in listed.content
        assert 'https://example/mcp' in listed.content

        mgr = MCPConfigManager(str(isolate_home), None)
        assert 'docs' in mgr.list('global')

        disabled = await router.dispatch(
            make_ctx('/mcp disable docs global', runtime))
        assert 'disable docs' in disabled.content
        listed = await router.dispatch(make_ctx('/mcp list global', runtime))
        assert '[off] docs' in listed.content

    @pytest.mark.asyncio
    async def test_add_project_needs_work_dir(self):
        result = await make_router().dispatch(
            make_ctx('/mcp add local command=npx', MockRuntime()))
        assert 'work dir' in result.content

    @pytest.mark.asyncio
    async def test_add_project_writes_mcp_json(self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx('/mcp add local command=npx', runtime))
        assert 'Added local' in result.content
        assert '(project)' in result.content
        assert 'Settings' in result.content
        mgr = MCPConfigManager(str(isolate_home), str(work))
        entry = mgr.list('project')['local']
        assert entry['command'] == 'npx'
        assert entry['args'] == []

    @pytest.mark.asyncio
    async def test_add_sees_work_dir_on_agent_runtime(self, tmp_path,
                                                      isolate_home):
        """Live TUI passes Runtime(llm=...), not a fake agent with .config."""
        from types import SimpleNamespace
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = SimpleNamespace(
            llm=SimpleNamespace(
                config=OmegaConf.create({'output_dir': str(work)})))
        result = await make_router().dispatch(
            make_ctx('/mcp add live url=https://example/mcp', runtime))
        assert 'Added live (project)' in result.content
        mgr = MCPConfigManager(str(isolate_home), str(work))
        assert 'live' in mgr.list('project')

    @pytest.mark.asyncio
    async def test_add_splits_stdio_command_line(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx(
                '/mcp add fetch global command="npx -y @mcp/server-fetch"',
                MockRuntime()))
        assert 'Added fetch' in result.content
        entry = MCPConfigManager(str(isolate_home), None).list('global')['fetch']
        assert entry['command'] == 'npx'
        assert entry['args'] == ['-y', '@mcp/server-fetch']

    @pytest.mark.asyncio
    async def test_list_without_work_dir_does_not_crash(self, isolate_home):
        await make_router().dispatch(
            make_ctx('/mcp add docs global url=https://example/mcp', MockRuntime()))
        result = await make_router().dispatch(
            make_ctx('/mcp list', MockRuntime()))
        assert 'docs' in result.content

    @pytest.mark.asyncio
    async def test_update_changes_url(self, isolate_home):
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/mcp add docs global url=https://example/mcp',
                runtime=runtime))
        result = await router.dispatch(
            make_ctx(
                '/mcp update docs global url=https://example/v2',
                runtime=runtime))
        assert 'Updated docs' in result.content
        entry = MCPConfigManager(str(isolate_home), None).list('global')['docs']
        assert entry['url'] == 'https://example/v2'


class TestSkillsCommand:
    @pytest.mark.asyncio
    async def test_help(self):
        result = await make_router().dispatch(make_ctx('/skills'))
        assert result.content.startswith('No skills.')
        assert '/skills add' in result.content

    @pytest.mark.asyncio
    async def test_add_copies_into_live_tree(self, tmp_path, isolate_home):
        src = tmp_path / 'my-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# Hello\n')
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx(f'/skills add {src} global', runtime))
        assert 'Imported: my-skill' in result.content
        dest = SkillsConfigManager(str(isolate_home)).global_skills_tree()
        assert (dest / 'my-skill' / 'SKILL.md').is_file()

    @pytest.mark.asyncio
    async def test_remove_deletes_managed_copy(self, tmp_path, isolate_home):
        src = tmp_path / 'my-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# Hello\n')
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(make_ctx(f'/skills add {src} global', runtime))
        result = await router.dispatch(
            make_ctx('/skills remove my-skill global', runtime))
        assert 'Removed managed skill my-skill' in result.content
        dest = SkillsConfigManager(str(isolate_home)).global_skills_tree()
        assert not (dest / 'my-skill').exists()
        # Original import source is untouched.
        assert (src / 'SKILL.md').is_file()

    @pytest.mark.asyncio
    async def test_remove_non_managed_does_not_rmtree(self):
        result = await make_router().dispatch(
            make_ctx('/skills remove ghost global', MockRuntime()))
        assert 'not a managed skill' in result.content

    @pytest.mark.asyncio
    async def test_disable_writes_skills_json_even_with_runtime(
            self, isolate_home):
        class FakeRuntime:
            def toggle(self, skill_id, enabled):
                raise AssertionError('must persist via SkillsConfigManager')

            def list_all(self):
                return []

            def sync_with_config(self, _cfg):
                pass

            def reload_all(self):
                pass

        runtime = MockRuntime(_skill_runtime=FakeRuntime())
        await make_router().dispatch(
            make_ctx('/skills disable demo global', runtime))
        data = SkillsConfigManager(str(isolate_home)).load_global()
        assert 'demo' in data.get('disabled', [])

    @pytest.mark.asyncio
    async def test_add_without_scope_uses_project_when_work_dir(
            self, tmp_path, isolate_home):
        src = tmp_path / 'ask-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# ask\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx(f'/skills add {src}', runtime))
        assert 'Imported: ask-skill (project)' in result.content
        assert (work / '.ms_agent' / 'skills' / 'ask-skill' / 'SKILL.md').is_file()
        assert not (isolate_home / 'skills' / 'ask-skill').exists()

    @pytest.mark.asyncio
    async def test_add_without_work_dir_defaults_global(
            self, tmp_path, isolate_home):
        src = tmp_path / 'solo-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# solo\n')
        result = await make_router().dispatch(
            make_ctx(f'/skills add {src}', MockRuntime()))
        assert 'Imported: solo-skill (global)' in result.content
        dest = SkillsConfigManager(str(isolate_home)).global_skills_tree()
        assert (dest / 'solo-skill' / 'SKILL.md').is_file()

    @pytest.mark.asyncio
    async def test_enable_without_scope_uses_same_default_as_add(
            self, tmp_path, isolate_home):
        src = tmp_path / 'only-here'
        src.mkdir()
        (src / 'SKILL.md').write_text('# only\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        router = make_router()
        await router.dispatch(
            make_ctx(f'/skills add {src}', runtime))
        result = await router.dispatch(
            make_ctx('/skills disable only-here', runtime))
        assert 'disable only-here (project)' in result.content
        proj = SkillsConfigManager(str(isolate_home)).load_project(str(work))
        assert 'only-here' in proj.get('disabled', [])
        glob = SkillsConfigManager(str(isolate_home)).load_global()
        assert 'only-here' not in glob.get('disabled', [])

    @pytest.mark.asyncio
    async def test_list_without_runtime_shows_live_tree_ids(
            self, tmp_path, isolate_home):
        src = tmp_path / 'shown-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# Shown\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        router = make_router()
        await router.dispatch(
            make_ctx(f'/skills add {src} global', runtime))
        listed = await router.dispatch(make_ctx('/skills list', runtime))
        assert 'shown-skill' in listed.content
        assert listed.content.strip().startswith('Skills:')
        assert 'Sources:' not in listed.content

    @pytest.mark.asyncio
    async def test_disable_skill_named_project_is_not_a_scope(
            self, tmp_path, isolate_home):
        src = tmp_path / 'project'
        src.mkdir()
        (src / 'SKILL.md').write_text('# project\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        router = make_router()
        await router.dispatch(
            make_ctx(f'/skills add {src} project', runtime))
        result = await router.dispatch(
            make_ctx('/skills disable project', runtime))
        assert 'disable project (project)' in result.content
        proj = SkillsConfigManager(str(isolate_home)).load_project(str(work))
        assert 'project' in proj.get('disabled', [])

    @pytest.mark.asyncio
    async def test_alias_skill_mgr(self):
        result = await make_router().dispatch(make_ctx('/skill-mgr'))
        assert '/skills add' in result.content
