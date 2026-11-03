"""TUI /search writes the same tools.web_search block WebUI uses."""
import json

import pytest

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
        assert 'WebUI' not in result.content
        assert 'MS_AGENT_HOME' not in result.content

    @pytest.mark.asyncio
    async def test_list_marks_current(self):
        result = await make_router().dispatch(make_ctx('/search list'))
        assert '* tavily' in result.content
        assert 'arxiv' not in result.content.lower()

    @pytest.mark.asyncio
    async def test_engine_writes_settings_json(self, isolate_home):
        result = await make_router().dispatch(
            make_ctx('/search engine exa'))
        assert 'Engine → exa' in result.content
        assert '/new' not in result.content
        assert 'restart' not in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['engine'] == 'exa'

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
    async def test_arxiv_is_not_an_option(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/search engine arxiv'))
        assert 'Unknown search engine: arxiv' in result.content
        assert 'tavily' in result.content
        assert 'arxiv, ' not in result.content
        assert not (isolate_home / 'settings.json').exists()

    @pytest.mark.asyncio
    async def test_disable(self, isolate_home):
        result = await make_router().dispatch(make_ctx('/search disable'))
        assert 'disabled' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['enabled'] is False

    @pytest.mark.asyncio
    async def test_missing_package_stays_keyless_and_says_how_to_install(
            self, monkeypatch):
        def missing(engine):
            return {'exa': 'exa-py'}.get(engine)

        monkeypatch.setattr(
            'ms_agent.tools.search.availability._missing_pip', missing)
        listed = await make_router().dispatch(make_ctx('/search list'))
        assert 'arxiv' not in listed.content.lower()
        tavily_row = next(line for line in listed.content.splitlines()
                          if ' Tavily ' in line)
        assert 'keyless-ok' in tavily_row
        assert 'UNAVAILABLE' not in tavily_row

        await make_router().dispatch(make_ctx('/search engine exa'))
        bare = await make_router().dispatch(make_ctx('/search'))
        assert 'UNAVAILABLE' not in bare.content
        await make_router().dispatch(make_ctx('/search key sk-test'))
        keyed = await make_router().dispatch(make_ctx('/search'))
        assert ('UNAVAILABLE: Package `exa-py` is not installed. '
                'Run: pip install exa-py, then restart ms-agent.'
                ) in keyed.content

    @pytest.mark.asyncio
    async def test_engine_switch_does_not_need_runtime_config(
            self, isolate_home):
        from ms_agent.agent.runtime import Runtime
        runtime = Runtime()
        result = await make_router().dispatch(
            make_ctx('/search engine serpapi', runtime))
        assert 'Engine → serpapi' in result.content
        data = json.loads((isolate_home / 'settings.json').read_text())
        assert data['tools']['web_search']['engine'] == 'serpapi'
        assert not hasattr(runtime, 'config')
