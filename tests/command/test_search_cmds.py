"""TUI /search writes the same tools.web_search block WebUI uses."""
import json

import pytest
from omegaconf import OmegaConf

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext


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
    return home


class TestSearchCommand:
    @pytest.mark.asyncio
    async def test_default_status(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/search'))
        assert 'Engine: tavily' in result.content
        assert '/search engine' in result.content
        assert str(isolate_home) in result.content
        assert 'MS_AGENT_HOME' in result.content

    @pytest.mark.asyncio
    async def test_list_marks_current(self):
        result = await make_router().dispatch(make_ctx('/search list'))
        assert '* tavily' in result.content
        assert 'arxiv' in result.content

    @pytest.mark.asyncio
    async def test_engine_writes_settings_json(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/search engine arxiv'))
        assert 'Engine → arxiv' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['engine'] == 'arxiv'

    @pytest.mark.asyncio
    async def test_key_is_per_engine(self, isolate_home):
        await make_router().dispatch(make_ctx('/search engine exa'))
        result = await make_router().dispatch(
            make_ctx('/search key sk-exa-test'))
        assert 'saved' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['exa_api_key'] == 'sk-exa-test'
        await make_router().dispatch(make_ctx('/search engine tavily'))
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['engine'] == 'tavily'
        assert data['tools']['web_search']['exa_api_key'] == 'sk-exa-test'

    @pytest.mark.asyncio
    async def test_key_clear(self, isolate_home):
        await make_router().dispatch(make_ctx('/search engine exa'))
        await make_router().dispatch(make_ctx('/search key abc'))
        result = await make_router().dispatch(make_ctx('/search key clear'))
        assert 'cleared' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert 'exa_api_key' not in data['tools']['web_search']

    @pytest.mark.asyncio
    async def test_arxiv_rejects_key(self):
        await make_router().dispatch(make_ctx('/search engine arxiv'))
        result = await make_router().dispatch(make_ctx('/search key nope'))
        assert 'does not use an API key' in result.content

    @pytest.mark.asyncio
    async def test_disable(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/search disable'))
        assert 'disabled' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['enabled'] is False

    @pytest.mark.asyncio
    async def test_updates_runtime_config(self):
        runtime = type('R', (), {'config': OmegaConf.create({})})()
        await make_router().dispatch(
            make_ctx('/search engine serpapi', runtime))
        assert runtime.config.tools.web_search.engine == 'serpapi'
