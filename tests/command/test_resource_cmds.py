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


class _Failure:
    def __init__(self, status, last_error):
        self.status = status
        self.last_error = last_error
        self.enabled = True


class _FailureRuntime:
    """In-memory connect result. Listing it must not open a connection."""

    def __init__(self, states):
        self._states = states
        self.connects = []

    def get_server(self, name):
        return self._states.get(name)

    async def connect_single_server(self, *args, **kwargs):
        self.connects.append(args)
        raise AssertionError('list/get must not connect')


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
        assert 'Saved for this folder' in result.content
        assert 'WebUI' not in result.content
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
    async def test_list_rejects_an_extra_name(self, isolate_home):
        await make_router().dispatch(
            make_ctx(
                '/mcp add docs global url=https://example/mcp',
                MockRuntime()))
        result = await make_router().dispatch(
            make_ctx('/mcp list mem1', MockRuntime()))
        assert 'Unknown list option.' in result.content
        assert 'Need: /mcp list [global|project]' in result.content
        assert 'Got:  /mcp list mem1' in result.content
        assert 'docs' not in result.content
        assert 'https://example/mcp' not in result.content

    @pytest.mark.asyncio
    async def test_list_shows_a_recorded_failure_but_not_by_name(
            self, isolate_home):
        runtime = MockRuntime()
        runtime._mcp_runtime = _FailureRuntime({
            'slow': _Failure('error', '6秒内没有连上'),
        })
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/mcp add slow global url=http://10.255.255.1/mcp',
                runtime))
        listed = await router.dispatch(make_ctx('/mcp list', runtime))
        assert ('[on] slow  http://10.255.255.1/mcp  未连接  '
                '6秒内没有连上') in listed.content
        by_name = await router.dispatch(make_ctx('/mcp list slow', runtime))
        assert 'Unknown list option.' in by_name.content
        assert '6秒内没有连上' not in by_name.content
        assert '10.255.255.1' not in by_name.content
        assert runtime._mcp_runtime.connects == []

    @pytest.mark.asyncio
    async def test_get_shows_the_skip_line_without_connecting(
            self, isolate_home):
        runtime = MockRuntime()
        runtime._mcp_runtime = _FailureRuntime({
            'slow': _Failure('error', '6秒内没有连上'),
        })
        await make_router().dispatch(
            make_ctx(
                '/mcp add slow global url=http://10.255.255.1/mcp',
                runtime))
        result = await make_router().dispatch(
            make_ctx('/mcp get slow', runtime))
        assert 'url: http://10.255.255.1/mcp' in result.content
        assert 'status: 未连接' in result.content
        assert 'last_error: 6秒内没有连上' in result.content
        assert '本轮先不用' not in result.content
        assert result.content.index('status:') > result.content.index('url:')
        assert runtime._mcp_runtime.connects == []

    @pytest.mark.asyncio
    async def test_list_and_get_show_a_dead_process(self, isolate_home):
        state = _Failure('connecting', '进程已退出')
        state.process_exited = True
        state.tool_count = 0
        state.config = {'command': 'npx'}
        runtime = MockRuntime()
        runtime._mcp_runtime = _FailureRuntime({'mem': state})
        await make_router().dispatch(
            make_ctx('/mcp add mem global command=npx', runtime))
        listed = await make_router().dispatch(make_ctx('/mcp list', runtime))
        assert '[on] mem  npx  进程已退出' in listed.content
        assert '本轮先不用' not in listed.content
        got = await make_router().dispatch(make_ctx('/mcp get mem', runtime))
        assert 'status: 进程已退出' in got.content
        assert 'tools: 0' in got.content
        assert 'process: 不在' in got.content
        assert '本轮先不用' not in got.content

    @pytest.mark.asyncio
    async def test_retry_reports_status_and_does_not_talk_in_chat(
            self, isolate_home):
        state = _Failure('error', '6秒内没有连上')
        state.tool_count = 0

        class _Retry(_FailureRuntime):

            async def retry_server(self, name):
                self.connects.append(name)
                current = self._states[name]
                current.status = 'connecting'
                current.last_error = None
                return current

        runtime = MockRuntime()
        runtime._mcp_runtime = _Retry({'slow': state})
        await make_router().dispatch(
            make_ctx(
                '/mcp add slow global url=http://10.255.255.1/mcp',
                runtime))
        result = await make_router().dispatch(
            make_ctx('/mcp retry slow', runtime))
        assert result.content == 'slow: 启动中'
        assert runtime._mcp_runtime.connects == ['slow']

    @pytest.mark.asyncio
    async def test_list_scope_word_names_the_other_copy(
            self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        await make_router().dispatch(
            make_ctx(
                '/mcp add project global url=https://example/mcp',
                runtime))
        listed = await make_router().dispatch(
            make_ctx('/mcp list project', runtime))
        assert listed.content.startswith('名叫 project 的服务器不在这份清单里。')
        assert 'https://example/mcp' not in listed.content

    @pytest.mark.asyncio
    async def test_get_shows_one_server(self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        mgr = MCPConfigManager(str(isolate_home), str(work))
        mgr.add(
            'docs',
            {
                'url': 'https://sk-THIS-IS-A-REAL-KEY-99@example/mcp',
                'headers': {
                    'Authorization': 'Bearer sk-THIS-IS-A-REAL-KEY-99',
                    'Content-Type': 'application/json',
                },
                'env': {
                    'PATH': '/usr/bin',
                    'API_KEY': 'sk-THIS-IS-A-REAL-KEY-99',
                },
            },
            scope='global',
        )
        mgr.add(
            'docs',
            {'command': 'npx', 'args': ['-y', 'server']},
            scope='project',
        )
        result = await make_router().dispatch(
            make_ctx('/mcp get docs', runtime))
        assert 'docs (global):' in result.content
        assert 'docs (project):' in result.content
        assert 'enabled: on' in result.content
        assert 'url: https://[REDACTED:api_key]@example/mcp' in result.content
        assert 'Content-Type: application/json' in result.content
        assert 'PATH: /usr/bin' in result.content
        assert 'command: npx' in result.content
        assert 'args: -y server' in result.content
        assert 'sk-THIS-IS-A-REAL-KEY-99' not in result.content
        assert 'Authorization: ***' in result.content
        assert 'API_KEY: ***' in result.content

    @pytest.mark.asyncio
    async def test_get_one_scope_and_a_missing_name(self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        await make_router().dispatch(
            make_ctx(
                '/mcp add project global url=https://example/mcp',
                runtime))
        one = await make_router().dispatch(
            make_ctx('/mcp get project global', runtime))
        assert 'project (global):' in one.content
        assert 'url: https://example/mcp' in one.content
        assert 'project (project):' not in one.content
        missing = await make_router().dispatch(
            make_ctx('/mcp get mem1', runtime))
        assert 'No MCP server named mem1.' in missing.content
        assert 'Need: /mcp get <name> [global|project]' in missing.content

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
    async def test_list_uses_the_loaded_runtime_before_disk(self, isolate_home):
        class Loaded:
            def list_all(self):
                return [{
                    'skill_id': 'from-session',
                    'name': 'Loaded',
                    'enabled': True,
                }]

        runtime = MockRuntime(_skill_runtime=Loaded())
        result = await make_router().dispatch(
            make_ctx('/skills list', runtime))
        assert '[on] from-session  Loaded' in result.content
        assert 'No skills' not in result.content

    @pytest.mark.asyncio
    async def test_list_scans_disk_before_skills_are_loaded(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/skills list', MockRuntime()))
        assert 'from-session' not in result.content

    def test_loaded_skills_are_published_on_the_session(self):
        from types import SimpleNamespace

        from ms_agent.agent.llm_agent import LLMAgent
        agent = LLMAgent.__new__(LLMAgent)
        agent.runtime = SimpleNamespace()
        agent._skill_runtime = SimpleNamespace(marker=1)
        agent._skill_catalog = SimpleNamespace()
        agent._command_router = None
        agent._plugin_runtime = None
        agent._publish_skill_runtime()
        assert agent.runtime._skill_runtime is agent._skill_runtime
        agent.runtime = None
        agent._publish_skill_runtime()

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
    async def test_add_without_scope_lands_on_this_machine(
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
        assert 'Imported: ask-skill (global)' in result.content
        assert (isolate_home / 'skills' / 'ask-skill' / 'SKILL.md').is_file()
        assert not (work / '.ms_agent' / 'skills' / 'ask-skill').exists()

    @pytest.mark.asyncio
    async def test_add_menu_can_place_the_skill_in_this_folder(
            self, tmp_path, isolate_home):
        src = tmp_path / 'ask-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# ask\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))

        def choose(labels, header):
            assert labels == ['这台机器', '这个文件夹']
            assert header == '新技能放到哪里？'
            return '这个文件夹'

        result = await make_router().dispatch(
            make_ctx(
                f'/skills add {src}',
                runtime,
                extra={'choose_scope': choose}))
        assert 'Imported: ask-skill (project)' in result.content
        assert (work / '.ms_agent' / 'skills' / 'ask-skill' / 'SKILL.md').is_file()
        assert not (isolate_home / 'skills' / 'ask-skill').exists()

    @pytest.mark.asyncio
    async def test_add_on_production_runtime_does_not_raise(
            self, tmp_path, isolate_home):
        from ms_agent.agent.runtime import Runtime
        src = tmp_path / 'demo-skill'
        src.mkdir()
        (src / 'SKILL.md').write_text('# demo\n')
        result = await make_router().dispatch(
            make_ctx(f'/skills add {src} global', Runtime()))
        assert 'Imported: demo-skill (global)' in result.content
        dest = SkillsConfigManager(str(isolate_home)).global_skills_tree()
        assert (dest / 'demo-skill' / 'SKILL.md').is_file()

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
    async def test_disable_without_scope_follows_the_added_copy(
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
        assert 'disable only-here (global)' in result.content
        glob = SkillsConfigManager(str(isolate_home)).load_global()
        assert 'only-here' in glob.get('disabled', [])
        proj = SkillsConfigManager(str(isolate_home)).load_project(str(work))
        assert 'only-here' not in proj.get('disabled', [])

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
    async def test_disable_without_scope_follows_a_folder_copy(
            self, tmp_path, isolate_home):
        mgr = SkillsConfigManager(str(isolate_home))
        work = tmp_path / 'repo'
        work.mkdir()
        skill = mgr.project_skills_tree(str(work)) / 'folder-only'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('# folder\n')
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx('/skills disable folder-only', runtime))
        assert 'disable folder-only (project)' in result.content
        project = mgr.load_project(str(work))
        assert 'folder-only' in (project.get('disabled') or [])
        assert 'folder-only' not in (mgr.load_global().get('disabled') or [])
        assert not (mgr.global_skills_tree() / 'folder-only').exists()

    @pytest.mark.asyncio
    async def test_enable_without_scope_uses_existing_global_copy(
            self, tmp_path, isolate_home):
        mgr = SkillsConfigManager(str(isolate_home))
        skill = mgr.global_skills_tree() / 'g-only'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('# G\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        router = make_router()
        disabled = await router.dispatch(
            make_ctx('/skills disable g-only global', runtime))
        assert 'disable g-only (global)' in disabled.content
        enabled = await router.dispatch(
            make_ctx('/skills enable g-only', runtime))
        assert 'enable g-only (global)' in enabled.content
        assert 'g-only' not in (mgr.load_global().get('disabled') or [])
        project = mgr.load_project(str(work))
        assert 'g-only' not in (project.get('disabled') or [])

    @pytest.mark.asyncio
    async def test_remove_without_scope_deletes_existing_global_copy(
            self, tmp_path, isolate_home):
        mgr = SkillsConfigManager(str(isolate_home))
        skill = mgr.global_skills_tree() / 'g-only'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('# G\n')
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx('/skills remove g-only', runtime))
        assert 'Removed managed skill g-only' in result.content
        assert 'not a managed skill' not in result.content
        assert not skill.exists()

    @pytest.mark.asyncio
    async def test_enable_without_scope_asks_when_both_copies_exist(
            self, tmp_path, isolate_home):
        mgr = SkillsConfigManager(str(isolate_home))
        work = tmp_path / 'repo'
        work.mkdir()
        for root in (
                mgr.global_skills_tree(),
                mgr.project_skills_tree(str(work)),
        ):
            skill = root / 'g-only'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('# G\n')
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx('/skills enable g-only', runtime))
        assert 'both global and project' in result.content
        assert 'Pass global or project.' in result.content
        assert 'g-only' not in (mgr.load_global().get('disabled') or [])
        project = mgr.load_project(str(work))
        assert 'g-only' not in (project.get('disabled') or [])

    @pytest.mark.asyncio
    async def test_both_copies_menu_changes_only_the_chosen_one(
            self, tmp_path, isolate_home):
        mgr = SkillsConfigManager(str(isolate_home))
        work = tmp_path / 'repo'
        work.mkdir()
        for root in (
                mgr.global_skills_tree(),
                mgr.project_skills_tree(str(work)),
        ):
            skill = root / 'g-only'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('# G\n')
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))

        def choose(labels, header):
            assert labels == ['这台机器', '这个文件夹']
            assert '两处都有' in header
            return '这个文件夹'

        result = await make_router().dispatch(
            make_ctx(
                '/skills disable g-only',
                runtime,
                extra={'choose_scope': choose}))
        assert 'disable g-only (project)' in result.content
        assert 'g-only' not in (mgr.load_global().get('disabled') or [])
        project = mgr.load_project(str(work))
        assert 'g-only' in (project.get('disabled') or [])

    @pytest.mark.asyncio
    async def test_mcp_add_server_named_project(self, tmp_path, isolate_home):
        work = tmp_path / 'repo'
        work.mkdir()
        runtime = MockRuntime(
            config=OmegaConf.create({'output_dir': str(work)}))
        result = await make_router().dispatch(
            make_ctx(
                '/mcp add project url=https://example.invalid/mcp', runtime))
        assert 'Added project (project)' in result.content
        assert 'Need:' not in result.content

    @pytest.mark.asyncio
    async def test_alias_skill_mgr(self):
        result = await make_router().dispatch(make_ctx('/skill-mgr'))
        assert '/skills add' in result.content
