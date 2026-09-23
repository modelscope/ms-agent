"""TUI /instruction and /profile write the same files WebUI settings use."""
import pytest
from omegaconf import OmegaConf

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


def _runtime(work):
    return type('R', (), {
        'config': OmegaConf.create({'output_dir': str(work)}),
    })()


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('MS_AGENT_HOME', str(home))
    wf.reset_cache()
    yield home
    wf.reset_cache()


class TestInstructionCommand:
    @pytest.mark.asyncio
    async def test_show_empty(self, tmp_path):
        runtime = _runtime(tmp_path / 'work')
        (tmp_path / 'work').mkdir()
        result = await make_router().dispatch(make_ctx('/instruction', runtime))
        assert 'Global' in result.content
        assert 'Project' in result.content
        assert '(empty)' in result.content

    @pytest.mark.asyncio
    async def test_global_writes_agents_md(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/instruction global Always answer in French.'))
        assert 'saved' in result.content.lower()
        text = (isolate_home / 'AGENTS.md').read_text(encoding='utf-8')
        assert 'Always answer in French.' in text
        assert text.lstrip().startswith('---')
        shown = await make_router().dispatch(make_ctx('/instruction global'))
        assert 'Always answer in French.' in shown.content

    @pytest.mark.asyncio
    async def test_project_writes_private_slot_only(self, tmp_path):
        work = tmp_path / 'repo'
        work.mkdir()
        root = work / 'AGENTS.md'
        root.write_text('# team\nkeep me\n', encoding='utf-8')
        result = await make_router().dispatch(
            make_ctx('/instruction project Use FastAPI.', _runtime(work)))
        assert 'saved' in result.content.lower()
        private = work / '.ms_agent' / 'AGENTS.md'
        assert private.read_text(encoding='utf-8').strip() == 'Use FastAPI.'
        assert root.read_text(encoding='utf-8') == '# team\nkeep me\n'

    @pytest.mark.asyncio
    async def test_project_clear(self, tmp_path):
        work = tmp_path / 'repo'
        work.mkdir()
        await make_router().dispatch(
            make_ctx('/instruction project hello', _runtime(work)))
        result = await make_router().dispatch(
            make_ctx('/instruction project clear', _runtime(work)))
        assert 'cleared' in result.content.lower()
        assert (work / '.ms_agent' / 'AGENTS.md').read_text(
            encoding='utf-8').strip() == ''

    @pytest.mark.asyncio
    async def test_project_requires_work_dir(self):
        result = await make_router().dispatch(
            make_ctx('/instruction project hello'))
        assert 'work dir' in result.content.lower()

    @pytest.mark.asyncio
    async def test_alias_ins(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/ins global Be brief.'))
        assert 'saved' in result.content.lower()
        assert 'Be brief.' in (isolate_home / 'AGENTS.md').read_text('utf-8')


class TestProfileCommand:
    @pytest.mark.asyncio
    async def test_callme_and_about(self, isolate_home):
        await make_router().dispatch(make_ctx('/profile callme Alice'))
        result = await make_router().dispatch(
            make_ctx('/profile about I work on agents.'))
        assert 'saved' in result.content.lower()
        text = (isolate_home / 'PROFILE.md').read_text(encoding='utf-8')
        assert '- Call me: Alice' in text
        assert 'I work on agents.' in text
        shown = await make_router().dispatch(make_ctx('/profile'))
        assert 'Alice' in shown.content
        assert 'I work on agents.' in shown.content

    @pytest.mark.asyncio
    async def test_callme_clear_keeps_about(self, isolate_home):
        await make_router().dispatch(make_ctx('/profile callme Alice'))
        await make_router().dispatch(make_ctx('/profile about researcher'))
        await make_router().dispatch(make_ctx('/profile callme clear'))
        call_me, about = wf.read_profile()
        assert call_me == ''
        assert about == 'researcher'

    @pytest.mark.asyncio
    async def test_quoted_about(self, isolate_home):
        await make_router().dispatch(
            make_ctx('/profile about "line one and two"'))
        _, about = wf.read_profile()
        assert about == 'line one and two'
