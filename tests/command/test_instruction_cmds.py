"""TUI /profile shows where AGENTS.md and PROFILE.md live."""
import pytest

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext
from ms_agent.prompting import workspace_files as wf


def make_router():
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def make_ctx(text, runtime=None):
    router = make_router()
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='cli',
        runtime=runtime,
        extra={'router': router},
    )


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    wf.reset_cache()
    yield home
    wf.reset_cache()


class TestProfileCommand:
    @pytest.mark.asyncio
    async def test_show_lists_file_locations(self, isolate_home):
        shown = await make_router().dispatch(make_ctx('/profile'))
        assert 'Global:' in shown.content
        assert 'Project:' in shown.content
        assert str(isolate_home / 'AGENTS.md') in shown.content
        assert str(isolate_home / 'PROFILE.md') in shown.content
        assert '<work>/.ms_agent/AGENTS.md' in shown.content
        assert 'repo root' not in shown.content.lower()
        assert 'callme' not in shown.content.lower()

    @pytest.mark.asyncio
    async def test_show_lists_project_agents_when_work_dir_is_known(
            self, isolate_home, tmp_path):
        work = tmp_path / 'repo'
        work.mkdir()
        shown = await make_router().dispatch(
            make_ctx('/profile', runtime=type('R', (), {
                'config': type('C', (), {'output_dir': str(work)})(),
            })()))
        assert str(isolate_home / 'AGENTS.md') in shown.content
        assert str(work / '.ms_agent' / 'AGENTS.md') in shown.content
        assert str(work / 'AGENTS.md') not in shown.content

    @pytest.mark.asyncio
    async def test_set_does_not_write(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/profile set Alice'))
        assert 'only shows' in result.content.lower()
        assert 'PROFILE.md' in result.content
        assert not (isolate_home / 'PROFILE.md').exists()

    @pytest.mark.asyncio
    async def test_instruction_command_removed(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/instruction global Be brief.'))
        assert result is None
        assert not (isolate_home / 'AGENTS.md').exists()
