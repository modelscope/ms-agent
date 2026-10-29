"""Tests for new builtin commands: /usage, /model, /config, /quit, /tools, /compact, /context."""
import json
import pytest
from dataclasses import dataclass, field
from typing import List

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResultType
from ms_agent.llm.utils import Message


from omegaconf import OmegaConf


def _make_mock_config():
    return OmegaConf.create({
        'llm': {
            'service': 'openai',
            'model': 'qwen3.7-plus',
            'openai_api_key': 'sk-test-secret-key',
        },
        'tools': {
            'file_system': {},
            'web_search': {},
            'code_executor': {},
            'plugins': ['tools/my_plugin.py'],
        },
        'generation_config': {'stream': True},
    })


@dataclass
class MockLLM:
    model: str = 'qwen3.7-plus'
    config: object = field(default_factory=_make_mock_config)


@dataclass
class MockRuntime:
    should_stop: bool = False
    round: int = 5
    tag: str = 'test'
    llm: MockLLM = field(default_factory=MockLLM)


def make_router():
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def _keyed(provider: str) -> None:
    from ms_agent.config.model_settings import ModelSettingsManager
    from ms_agent.project.paths import global_home
    ModelSettingsManager(global_home()).patch_provider(
        provider, api_key='sk-test', base_url='https://example.invalid/v1')


def _catalog_ok(monkeypatch, ids):
    from ms_agent.llm.model_discovery import CatalogProbe
    monkeypatch.setattr(
        'ms_agent.llm.model_discovery.probe_model_catalog',
        lambda *_a, **_k: CatalogProbe('ok', 200, list(ids)))


def make_ctx(text, runtime=None, messages=None):
    router = make_router()
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='cli',
        runtime=runtime,
        extra={'router': router, 'messages': messages},
    )


class TestUsage:
    @pytest.fixture(autouse=True)
    def _save_restore_tokens(self):
        from ms_agent.agent.llm_agent import LLMAgent
        saved = (
            LLMAgent.TOTAL_PROMPT_TOKENS,
            LLMAgent.TOTAL_COMPLETION_TOKENS,
            LLMAgent.TOTAL_REASONING_TOKENS,
        )
        yield
        (
            LLMAgent.TOTAL_PROMPT_TOKENS,
            LLMAgent.TOTAL_COMPLETION_TOKENS,
            LLMAgent.TOTAL_REASONING_TOKENS,
        ) = saved

    @pytest.mark.asyncio
    async def test_shows_token_counts(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.TOTAL_PROMPT_TOKENS = 1000
        LLMAgent.TOTAL_COMPLETION_TOKENS = 500
        LLMAgent.TOTAL_REASONING_TOKENS = 0
        router = make_router()
        ctx = make_ctx('/usage', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert result is not None
        assert '1,000' in result.content
        assert '500' in result.content
        assert '1,500' in result.content
        assert 'Rounds:            5' in result.content

    @pytest.mark.asyncio
    async def test_shows_reasoning_tokens(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.TOTAL_PROMPT_TOKENS = 2000
        LLMAgent.TOTAL_COMPLETION_TOKENS = 800
        LLMAgent.TOTAL_REASONING_TOKENS = 600
        router = make_router()
        ctx = make_ctx('/usage', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'Reasoning:       600' in result.content

    @pytest.mark.asyncio
    async def test_hides_reasoning_when_zero(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.TOTAL_PROMPT_TOKENS = 100
        LLMAgent.TOTAL_COMPLETION_TOKENS = 50
        LLMAgent.TOTAL_REASONING_TOKENS = 0
        router = make_router()
        ctx = make_ctx('/usage', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'Reasoning' not in result.content

    @pytest.mark.asyncio
    async def test_alias_stats(self):
        router = make_router()
        ctx = make_ctx('/stats', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.type == CommandResultType.MESSAGE


class TestModel:
    @pytest.fixture(autouse=True)
    def _isolate_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'ms_home'))
        for name in (
                'OPENAI_API_KEY',
                'DASHSCOPE_API_KEY',
                'ANTHROPIC_API_KEY',
                'MODELSCOPE_API_KEY',
                'MINIMAX_API_KEY',
        ):
            monkeypatch.delenv(name, raising=False)

    @pytest.mark.asyncio
    async def test_show_current_model(self):
        router = make_router()
        ctx = make_ctx('/model', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'qwen3.7-plus' in result.content
        assert 'openai' in result.content

    @pytest.mark.asyncio
    async def test_switch_model(self, monkeypatch):
        runtime = MockRuntime()
        router = make_router()
        _keyed('openai')
        _catalog_ok(monkeypatch, ['gpt-4o'])
        result = await router.dispatch(
            make_ctx('/model gpt-4o', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'gpt-4o' in result.content
        assert runtime.llm.model == 'gpt-4o'

    @pytest.mark.asyncio
    async def test_slash_in_model_id_stays_on_current_provider(self, monkeypatch):
        runtime = MockRuntime()
        router = make_router()
        _keyed('openai')
        _catalog_ok(monkeypatch, ['MiniMax/MiniMax-M2.1'])
        result = await router.dispatch(
            make_ctx('/model MiniMax/MiniMax-M2.1', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert runtime.llm.model == 'MiniMax/MiniMax-M2.1'
        assert runtime.llm.config.llm.service == 'openai'
        assert 'Provider: openai' in result.content
        assert 'Model:    MiniMax/MiniMax-M2.1' in result.content

    @pytest.mark.asyncio
    async def test_slash_does_not_select_a_provider(self, monkeypatch):
        runtime = MockRuntime()
        router = make_router()
        _keyed('openai')
        _catalog_ok(monkeypatch, ['Qwen/Qwen3.8-Flash-Next'])
        result = await router.dispatch(
            make_ctx('/model Qwen/Qwen3.8-Flash-Next', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert runtime.llm.config.llm.service == 'openai'
        assert runtime.llm.model == 'Qwen/Qwen3.8-Flash-Next'
        assert 'No provider named' not in result.content

    @pytest.mark.asyncio
    async def test_provider_slash_model_is_not_a_provider_switch(
            self, monkeypatch):
        runtime = MockRuntime()
        _keyed('openai')
        _catalog_ok(monkeypatch, ['gpt-4o'])
        result = await make_router().dispatch(
            make_ctx('/model dashscope/qwen-max', runtime=runtime))
        assert runtime.llm.config.llm.service == 'openai'
        assert runtime.llm.model != 'qwen-max'
        assert 'dashscope/qwen-max' in result.content
        assert 'No provider named' not in result.content

    @pytest.mark.asyncio
    async def test_space_form_sets_provider_when_model_has_slash(
            self, monkeypatch):
        runtime = MockRuntime()
        _keyed('dashscope')
        _catalog_ok(monkeypatch, ['MiniMax/MiniMax-M2.1'])
        result = await make_router().dispatch(
            make_ctx(
                '/model dashscope MiniMax/MiniMax-M2.1', runtime=runtime))
        assert runtime.llm.config.llm.service == 'dashscope'
        assert runtime.llm.model == 'MiniMax/MiniMax-M2.1'

    @pytest.mark.asyncio
    async def test_switch_provider_without_key_rolls_back(self, monkeypatch):
        monkeypatch.delenv('MINIMAX_API_KEY', raising=False)
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model minimax MiniMax-M2.1', runtime=runtime))
        assert result.type == CommandResultType.MESSAGE
        assert runtime.llm.config.llm.service == 'openai'
        assert runtime.llm.model == 'qwen3.7-plus'
        assert 'Cannot switch to:' in result.content
        assert 'Provider: minimax' in result.content
        assert 'Model:    MiniMax-M2.1' in result.content
        assert 'Still on:' in result.content
        assert 'Provider: openai' in result.content
        assert 'Model:    qwen3.7-plus' in result.content
        assert 'Set a key: /model provider key minimax <key>' in result.content
        assert 'Staying on' not in result.content
        assert 'keep that provider:\n  /model minimax MiniMax-M2.1' not in result.content
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        stored = ModelSettingsManager(global_home()).get_default_model()
        assert stored != 'minimax/MiniMax-M2.1'

    @pytest.mark.asyncio
    async def test_switch_fail_hints_keyed_provider(self, monkeypatch):
        for env in (
                'MINIMAX_API_KEY',
                'OPENAI_API_KEY',
                'DASHSCOPE_API_KEY',
                'ANTHROPIC_API_KEY',
                'MODELSCOPE_API_KEY',
                'GOOGLE_API_KEY',
                'GEMINI_API_KEY',
                'KIMI_API_KEY',
                'MOONSHOT_API_KEY',
                'DEEPSEEK_API_KEY',
                'OPENROUTER_API_KEY',
                'GLM_API_KEY',
                'ZHIPU_API_KEY',
                'ZHIPUAI_API_KEY',
        ):
            monkeypatch.delenv(env, raising=False)
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('no_catalog', 404, []))
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk url=https://acme/v1 protocol=openai',
                runtime=runtime))
        result = await router.dispatch(
            make_ctx('/model minimax MiniMax-M2.1', runtime=runtime))
        assert 'Or switch to a keyed provider (acme):' in result.content
        assert '/model acme <model>' in result.content
        assert '{provider_id}' not in result.content
        assert 'keep that provider' not in result.content

    @pytest.mark.asyncio
    async def test_same_provider_without_key_does_not_repeat_command(
            self, monkeypatch):
        monkeypatch.delenv('MINIMAX_API_KEY', raising=False)
        runtime = MockRuntime()
        runtime.llm.model = 'minimax MiniMax-M2.1'
        runtime.llm.config.llm.service = 'minimax'
        runtime.llm.config.llm.model = 'minimax MiniMax-M2.1'
        result = await make_router().dispatch(
            make_ctx('/model minimax MiniMax-M2.1', runtime=runtime))
        assert result.type == CommandResultType.MESSAGE
        assert runtime.llm.config.llm.service == 'minimax'
        assert runtime.llm.model == 'MiniMax-M2.1'
        assert runtime.llm.config.llm.model == 'MiniMax-M2.1'
        assert 'Already on:' in result.content
        assert 'Provider: minimax' in result.content
        assert 'Model:    MiniMax-M2.1' in result.content
        assert 'minimax MiniMax-M2.1' not in result.content
        assert 'Staying on' not in result.content
        assert '/model minimax MiniMax-M2.1' not in result.content
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        stored = ModelSettingsManager(global_home()).get_default_model()
        assert stored != 'minimax/minimax MiniMax-M2.1'

    @pytest.mark.asyncio
    async def test_show_strips_glued_provider_prefix(self, tmp_path):
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        home = tmp_path / 'ms_home'
        home.mkdir(parents=True, exist_ok=True)
        (home / 'settings.json').write_text(json.dumps({
            'default_model': 'minimax/minimax MiniMax-M2.1',
            'llm': {
                'provider': 'minimax',
                'model': 'minimax MiniMax-M2.1',
            },
        }))
        runtime = MockRuntime()
        runtime.llm.model = 'minimax MiniMax-M2.1'
        runtime.llm.config.llm.service = 'minimax'
        runtime.llm.config.llm.model = 'minimax MiniMax-M2.1'
        result = await make_router().dispatch(
            make_ctx('/model', runtime=runtime))
        assert 'Provider: minimax' in result.content
        assert 'Model:    MiniMax-M2.1' in result.content
        assert 'Model:    minimax MiniMax-M2.1' not in result.content
        assert 'Switch:   /model minimax MiniMax-M2.1' in result.content
        assert runtime.llm.model == 'MiniMax-M2.1'
        stored = ModelSettingsManager(global_home()).get_default_model()
        assert stored == 'minimax/MiniMax-M2.1'

    @pytest.mark.asyncio
    async def test_show_warns_when_live_client_differs(self):
        runtime = MockRuntime()
        runtime.llm.model = 'MiniMax-M2.1'
        runtime.llm.config.llm.service = 'minimax'
        runtime.llm.spec = type('S', (), {'name': 'dashscope'})()
        runtime.llm.transport = type(
            'T', (), {'base_url': 'https://dashscope.example/v1'})()
        result = await make_router().dispatch(
            make_ctx('/model', runtime=runtime))
        assert 'WARNING' in result.content
        assert 'dashscope' in result.content
        assert 'https://dashscope.example/v1' in result.content
        assert 'realign with /model dashscope MiniMax-M2.1.' in result.content
        assert 'dashscope/MiniMax-M2.1' not in result.content

    @pytest.mark.asyncio
    async def test_show_current_separates_provider_and_model(self):
        runtime = MockRuntime()
        runtime.llm.model = 'MiniMax/MiniMax-M2.1'
        runtime.llm.config.llm.service = 'dashscope'
        result = await make_router().dispatch(
            make_ctx('/model', runtime=runtime))
        assert 'Provider: dashscope' in result.content
        assert 'Model:    MiniMax/MiniMax-M2.1' in result.content
        assert 'Switch:   /model dashscope MiniMax/MiniMax-M2.1' in result.content

    @pytest.mark.asyncio
    async def test_switch_model_replaces_setup_stub(self, monkeypatch):
        from types import SimpleNamespace

        config = _make_mock_config()
        stub = SimpleNamespace(config=config, model='old', _setup_stub=True)
        runtime = MockRuntime(llm=stub)
        router = make_router()
        ctx = make_ctx('/model dashscope qwen3.8-flash', runtime=runtime)
        _keyed('dashscope')
        _catalog_ok(monkeypatch, ['qwen3.8-flash'])
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'Switch:   /model dashscope qwen3.8-flash' in result.content
        assert '/model dashscope/qwen3.8-flash' not in result.content
        assert runtime.llm.model == 'qwen3.8-flash'
        assert config.llm.service == 'dashscope'

    @pytest.mark.asyncio
    async def test_switch_model_persists_to_settings_not_project_patch(
            self, tmp_path, monkeypatch):
        # The committed source YAML must never be mutated by /model.
        yaml_text = (
            'llm:\n'
            '  service: openai\n'
            '  model: qwen3.5-plus\n'
            '  openai_api_key: <OPENAI_API_KEY>  # secret placeholder\n'
        )
        cfg_file = tmp_path / 'searcher.yaml'
        cfg_file.write_text(yaml_text, encoding='utf-8')

        config = OmegaConf.create({
            'llm': {'service': 'openai', 'model': 'qwen3.5-plus'},
            'local_dir': str(tmp_path),
            'output_dir': str(tmp_path),
            'name': 'searcher.yaml',
        })
        runtime = MockRuntime(llm=MockLLM(model='qwen3.5-plus', config=config))
        router = make_router()
        ctx = make_ctx('/model qwen3.7-max', runtime=runtime)
        _keyed('openai')
        _catalog_ok(monkeypatch, ['qwen3.7-max'])
        result = await router.dispatch(ctx)

        assert result.type == CommandResultType.MUTATE_STATE
        assert 'qwen3.7-max' in result.content
        assert 'Saved as the default' not in result.content
        assert '下一条消息使用它' not in result.content
        assert 'project patch' not in result.content.lower()

        # The source YAML is untouched.
        assert cfg_file.read_text(encoding='utf-8') == yaml_text

        # /model writes the WebUI-shared default only — not a folder pin that
        # would later hide a WebUI default change.
        patch_file = tmp_path / '.ms_agent' / 'config.yaml'
        assert not patch_file.exists()
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        assert ModelSettingsManager(global_home()).get_default_model() == (
            'openai/qwen3.7-max')

    @pytest.mark.asyncio
    async def test_switch_model_no_source_file(self, tmp_path, monkeypatch):
        # Still writes the WebUI-shared default_model in settings.json.
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/model gpt-4o', runtime=runtime)
        _keyed('openai')
        _catalog_ok(monkeypatch, ['gpt-4o'])
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'gpt-4o' in result.content
        assert 'Saved as the default' not in result.content
        assert '下一条消息使用它' not in result.content
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        assert ModelSettingsManager(global_home()).get_default_model() == 'openai/gpt-4o'

    @pytest.mark.asyncio
    async def test_switch_updates_this_session_and_the_default(
            self, tmp_path, monkeypatch):
        """Switching changes the shared default and this conversation.

        Another conversation's stored model stays put, so coming back to it
        does not follow the new default.
        """
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project import SessionManager
        from ms_agent.project.manager import ProjectManager
        from ms_agent.tui.app import TuiApp

        home = tmp_path / 'home'
        monkeypatch.setenv('MS_AGENT_HOME', str(home))
        work = tmp_path / 'repo'
        work.mkdir()
        project = TuiApp._open_project(str(work))
        sm = SessionManager(project)
        current = sm.create(model='qwen3.7-plus', model_provider='openai')
        other = sm.create(model='kept-model', model_provider='openai')
        config = OmegaConf.create({
            'llm': {
                'service': 'openai',
                'model': 'qwen3.7-plus',
                'openai_api_key': 'sk-test',
            },
            'session_log': {
                'dir': str(sm.sessions_dir / current.id),
            },
        })
        runtime = MockRuntime(llm=MockLLM(model='qwen3.7-plus', config=config))
        _keyed('openai')
        _catalog_ok(monkeypatch, ['gpt-4o'])
        result = await make_router().dispatch(
            make_ctx('/model gpt-4o', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert ModelSettingsManager(home).get_default_model() == 'openai/gpt-4o'
        stored = sm.get(current.id)
        assert stored.model == 'gpt-4o'
        assert stored.model_provider == 'openai'
        untouched = sm.get(other.id)
        assert untouched.model == 'kept-model'
        assert ProjectManager(str(home)).get(project.id) is not None

    @pytest.mark.asyncio
    async def test_model_list_reads_settings(self, tmp_path):
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        ModelSettingsManager(global_home()).set_default_model(
            'a-1', provider='acme')
        router = make_router()
        ctx = make_ctx('/model list', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'Default: /model acme a-1' in result.content
        assert 'acme/a-1' not in result.content
        assert 'Providers:' in result.content
        assert 'WebUI' not in result.content

    @pytest.mark.asyncio
    async def test_model_list_default_keeps_slash_inside_the_model_id(self):
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        ModelSettingsManager(global_home()).set_default_model(
            'Qwen/Qwen3.8-Flash-Next', provider='modelscope')
        result = await make_router().dispatch(
            make_ctx('/model list', runtime=MockRuntime()))
        assert ('Default: /model modelscope Qwen/Qwen3.8-Flash-Next'
                in result.content)
        assert 'modelscope/Qwen/' not in result.content

    @pytest.mark.asyncio
    async def test_model_list_does_not_fetch(self, monkeypatch):
        called = []

        def boom(*_a, **_k):
            called.append(1)
            return []

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.fetch_model_ids', boom)
        await make_router().dispatch(
            make_ctx('/model list', runtime=MockRuntime()))
        assert called == []

    @pytest.mark.asyncio
    async def test_model_list_live_filters_and_does_not_persist(
            self, tmp_path, monkeypatch):
        for env in (
                'DASHSCOPE_API_KEY',
                'MODELSCOPE_API_KEY',
                'OPENAI_API_KEY',
        ):
            monkeypatch.delenv(env, raising=False)
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('no_catalog', 404, []))
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk-secret url=https://acme/v1 protocol=openai',
                runtime=runtime))
        await router.dispatch(
            make_ctx('/model catalog add acme catalog-only', runtime=runtime))

        def fake(url, protocol, api_key):
            assert url == 'https://acme/v1'
            assert api_key == 'sk-secret'
            return [
                'qwen-plus',
                'qwen-vl-max',
                'wanx-v1',
                'text-embedding-v3',
            ]

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.fetch_model_ids', fake)
        result = await router.dispatch(
            make_ctx('/model list live acme', runtime=runtime))
        assert 'preview only' in result.content
        assert 'catalog: catalog-only' in result.content
        assert 'live: 2 chat' in result.content
        assert '      qwen-plus' in result.content
        assert '      qwen-vl-max' in result.content
        assert 'wanx-v1' not in result.content
        assert 'text-embedding-v3' not in result.content
        assert 'dropped' not in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['models'] == ['catalog-only']

        skipped = await router.dispatch(
            make_ctx('/model list live openai', runtime=runtime))
        assert 'skipped (no API key)' in skipped.content

    @pytest.mark.asyncio
    async def test_provider_add_set_key_catalog(self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('no_catalog', 404, []))
        runtime = MockRuntime()
        router = make_router()
        added = await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk-secret url=https://acme/v1 protocol=openai',
                runtime=runtime))
        assert 'Provider acme saved' in added.content
        assert 'Switch with /model acme <model>' in added.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['api_key'] == 'sk-secret'
        assert data['providers']['acme']['base_url'] == 'https://acme/v1'
        listed = await router.dispatch(make_ctx('/model list', runtime=runtime))
        assert 'sk-secret' not in listed.content
        assert 'key=sk-s****cret' in listed.content
        await router.dispatch(
            make_ctx('/model provider key acme sk-new', runtime=runtime))
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['api_key'] == 'sk-new'
        await router.dispatch(
            make_ctx('/model catalog add acme a-1', runtime=runtime))
        await router.dispatch(
            make_ctx('/model catalog remove acme a-1', runtime=runtime))
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert 'a-1' not in data['providers']['acme'].get('models', [])
        await router.dispatch(
            make_ctx('/model provider remove acme', runtime=runtime))
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert 'acme' not in data.get('providers', {})

    @pytest.mark.asyncio
    async def test_catalog_drop_uses_current_provider(self, tmp_path):
        runtime = MockRuntime()
        runtime.llm.config.llm.service = 'acme'
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk url=https://acme/v1 protocol=openai',
                runtime=runtime))
        await router.dispatch(
            make_ctx('/model catalog add acme qwen3.9-flash', runtime=runtime))
        dropped = await router.dispatch(
            make_ctx('/model catalog drop qwen3.9-flash', runtime=runtime))
        assert dropped.content == (
            'Removed qwen3.9-flash from acme catalog (current provider).')
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert 'qwen3.9-flash' not in data['providers']['acme'].get('models', [])

    @pytest.mark.asyncio
    async def test_catalog_unknown_action_does_not_dump_full_usage(self):
        result = await make_router().dispatch(
            make_ctx('/model catalog foo bar', runtime=MockRuntime()))
        assert 'Unknown catalog action' in result.content
        assert 'Need: /model catalog' in result.content
        assert '/model provider add' not in result.content

    @pytest.mark.asyncio
    async def test_catalog_remove_model_only_is_focused_without_override(self):
        result = await make_router().dispatch(
            make_ctx(
                '/model catalog remove qwen3.9-flash', runtime=MockRuntime()))
        assert 'Need: /model catalog remove <provider> <model>' in result.content
        assert '/model provider add' not in result.content

    @pytest.mark.asyncio
    async def test_catalog_remove_unknown_model_does_not_claim_success(
            self, tmp_path):
        runtime = MockRuntime()
        runtime.llm.config.llm.service = 'acme'
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk url=https://acme/v1 protocol=openai',
                runtime=runtime))
        await router.dispatch(
            make_ctx('/model catalog add acme qwen3.8-flash', runtime=runtime))
        result = await router.dispatch(
            make_ctx(
                '/model catalog remove qwen3.9-flash12', runtime=runtime))
        assert 'not in the acme catalog (current provider)' in result.content
        assert 'Pinned: qwen3.8-flash' in result.content
        assert 'Removed' not in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['models'] == ['qwen3.8-flash']

    @pytest.mark.asyncio
    async def test_catalog_no_args_lists_pinned(self, tmp_path):
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk url=https://acme/v1 protocol=openai',
                runtime=runtime))
        await router.dispatch(
            make_ctx('/model catalog add acme qwen3.8-flash', runtime=runtime))
        result = await router.dispatch(
            make_ctx('/model catalog', runtime=runtime))
        assert 'Pinned catalogs' in result.content
        assert 'acme: qwen3.8-flash' in result.content
        assert 'Need: /model catalog add|remove' in result.content

    @pytest.mark.asyncio
    async def test_provider_key_missing_args_is_focused(self):
        result = await make_router().dispatch(
            make_ctx('/model provider key', runtime=MockRuntime()))
        assert 'Need: /model provider key <provider> <key>|clear' in result.content
        assert 'Got:  /model provider key' in result.content
        assert '/model catalog add' not in result.content

    @pytest.mark.asyncio
    async def test_help_usage_example_is_dashscope_qwen(self):
        result = await make_router().dispatch(
            make_ctx('/model help', runtime=MockRuntime()))
        assert 'Example: /model dashscope qwen3.8-flash' in result.content
        assert 'e.g. dashscope' in result.content
        assert 'e.g. qwen3.8-flash' in result.content
        assert 'Saved in ' in result.content
        assert 'settings.json' in result.content
        assert 'WebUI' not in result.content
        assert 'MS_AGENT_HOME' not in result.content
        assert '<provider>' in result.content
        assert 'MiniMax' not in result.content
        assert '~/.ms_agent' not in result.content
        assert '<id>' not in result.content
        assert '<provider>/<model>' not in result.content

    @pytest.mark.asyncio
    async def test_list_unknown_option_is_focused(self):
        result = await make_router().dispatch(
            make_ctx('/model list foo', runtime=MockRuntime()))
        assert 'Need: /model list live [provider]' in result.content
        assert '/model provider add' not in result.content

    @pytest.mark.asyncio
    async def test_unknown_provider_action_is_focused(self):
        result = await make_router().dispatch(
            make_ctx('/model provider foo bar', runtime=MockRuntime()))
        assert "Unknown provider action 'foo'" in result.content
        assert 'Need: /model provider' in result.content
        assert '/model catalog add' not in result.content

    @pytest.mark.asyncio
    async def test_cannot_remove_builtin_without_override(self):
        result = await make_router().dispatch(
            make_ctx('/model provider remove openai', runtime=MockRuntime()))
        assert 'Cannot remove builtin' in result.content

    @pytest.mark.asyncio
    async def test_unknown_provider_prefix_is_rejected(self, tmp_path):
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model dashcope qwen-max', runtime=runtime))
        assert result.type == CommandResultType.MESSAGE
        assert 'No provider named dashcope' in result.content
        assert 'Known:' in result.content
        assert runtime.llm.model == 'qwen3.7-plus'
        assert runtime.llm.config.llm.model == 'qwen3.7-plus'
        settings = tmp_path / 'ms_home' / 'settings.json'
        if settings.exists():
            assert 'dashcope' not in settings.read_text()

    @pytest.mark.asyncio
    async def test_provider_word_ignores_case(self, monkeypatch):
        runtime = MockRuntime()
        _keyed('dashscope')
        _catalog_ok(monkeypatch, ['qwen-max'])
        result = await make_router().dispatch(
            make_ctx('/model DashScope qwen-max', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert runtime.llm.config.llm.service == 'dashscope'
        assert runtime.llm.model == 'qwen-max'
        assert 'No provider named' not in result.content

    @pytest.mark.asyncio
    async def test_runtime_only_key_still_checks_the_catalog(self, monkeypatch):
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        _catalog_ok(monkeypatch, ['gpt-4o'])
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model not-a-real-model', runtime=runtime))
        assert '列表里没有 not-a-real-model' in result.content
        assert runtime.llm.config.llm.model == 'qwen3.7-plus'

    @pytest.mark.asyncio
    async def test_runtime_only_key_notes_a_missing_catalog(self, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('no_catalog', 404, []))
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model some-model', runtime=runtime))
        assert '没有返回模型列表' in result.content
        assert 'Switched to' in result.content

    @pytest.mark.asyncio
    async def test_catalog_add_rejects_secret_shaped_model(self, tmp_path):
        runtime = MockRuntime()
        secret = 'sk-THIS-IS-MY-SECRET'
        result = await make_router().dispatch(
            make_ctx(f'/model catalog add {secret}', runtime=runtime))
        assert 'API key' in result.content
        assert secret not in result.content
        assert 'REDACTED' in result.content
        settings = tmp_path / 'ms_home' / 'settings.json'
        if settings.exists():
            assert secret not in settings.read_text()

    @pytest.mark.asyncio
    async def test_switch_rejects_secret_shaped_model(self):
        runtime = MockRuntime()
        secret = 'sk-THIS-IS-MY-SECRET'
        result = await make_router().dispatch(
            make_ctx(f'/model {secret}', runtime=runtime))
        assert 'API key' in result.content
        assert secret not in result.content
        assert runtime.llm.config.llm.model == 'qwen3.7-plus'

    @pytest.mark.asyncio
    async def test_provider_set_error_masks_secret(self):
        secret = 'sk-THIS-IS-MY-SECRET'
        result = await make_router().dispatch(
            make_ctx(f'/model provider set {secret}', runtime=MockRuntime()))
        assert 'No fields to patch' in result.content
        assert secret not in result.content
        assert 'REDACTED' in result.content

    @pytest.mark.asyncio
    async def test_no_runtime(self):
        router = make_router()
        ctx = make_ctx('/model', runtime=None)
        result = await router.dispatch(ctx)
        assert 'No active agent' in result.content


class TestConfig:
    @pytest.mark.asyncio
    async def test_shows_yaml(self):
        router = make_router()
        ctx = make_ctx('/config', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MESSAGE
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_alias_settings(self):
        router = make_router()
        ctx = make_ctx('/settings', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_masks_api_keys(self):
        router = make_router()
        ctx = make_ctx('/config', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'sk-test' not in result.content
        assert '***' in result.content

    @pytest.mark.asyncio
    async def test_masks_search_keys_and_mcp_headers(self):
        cfg = OmegaConf.create({
            'llm': {
                'service': 'openai',
                'model': 'gpt-4o',
                'openai_api_key': 'sk-real-key-value',
                'base_url':
                'https://user:sk-THIS-IS-A-REAL-KEY-99@gateway.example/v1',
                'openai_base_url':
                'https://sk-THIS-IS-A-REAL-KEY-99@gateway.example/v1',
            },
            'tools': {
                'web_search': {
                    'tavily_api_key': 'tvly-THIS-IS-MY-SECRET',
                },
            },
            'mcpServers': {
                'docs': {
                    'url': 'https://example.invalid/mcp',
                    'headers': {
                        'Authorization': 'Bearer THIS-IS-MY-TOKEN',
                        'Content-Type': 'application/json',
                        'X-Custom': 'keep-me',
                    },
                    'env': {
                        'PATH': '/usr/bin',
                    },
                },
            },
        })
        runtime = MockRuntime()
        runtime.llm.config = cfg
        result = await make_router().dispatch(
            make_ctx('/config', runtime=runtime))
        assert 'tvly-THIS-IS-MY-SECRET' not in result.content
        assert 'THIS-IS-MY-TOKEN' not in result.content
        assert 'sk-real-key-value' not in result.content
        assert 'tavily_api_key' in result.content
        assert 'Authorization' in result.content
        assert 'application/json' in result.content
        assert 'keep-me' in result.content
        assert '/usr/bin' in result.content
        assert 'sk-THIS-IS-A-REAL-KEY-99' not in result.content
        assert 'gateway.example/v1' in result.content
        assert 'https://user:[REDACTED:api_key]@gateway.example/v1' in (
            result.content)
        assert 'https://[REDACTED:api_key]@gateway.example/v1' in result.content


class TestQuit:
    @pytest.mark.asyncio
    async def test_sets_should_stop(self):
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/quit', runtime=runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.QUIT
        assert runtime.should_stop is True

    @pytest.mark.asyncio
    async def test_alias_exit(self):
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/exit', runtime=runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.QUIT


class TestTools:
    @pytest.mark.asyncio
    async def test_lists_tools(self):
        router = make_router()
        ctx = make_ctx('/tools', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'file_system' in result.content
        assert 'web_search' in result.content
        assert 'code_executor' in result.content
        assert '3' in result.content

    @pytest.mark.asyncio
    async def test_excludes_plugins_key(self):
        router = make_router()
        ctx = make_ctx('/tools', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'plugins' not in result.content

    @pytest.mark.asyncio
    async def test_connect_failure_is_not_listed_as_ready(self):
        runtime = MockRuntime()
        runtime.tool_manager = type('Mgr', (), {
            'connect_failures': {
                'web_search':
                'UNAVAILABLE: Package `arxiv` is not installed. '
                'Run: pip install arxiv, then restart ms-agent.',
            },
        })()
        result = await make_router().dispatch(
            make_ctx('/tools', runtime=runtime))
        file_row = next(line for line in result.content.splitlines()
                        if 'file_system' in line)
        assert 'UNAVAILABLE' not in file_row
        assert '• web_search  UNAVAILABLE: Package `arxiv`' in result.content
        assert '• code_executor' in result.content

    @pytest.mark.asyncio
    async def test_no_runtime(self):
        router = make_router()
        ctx = make_ctx('/tools', runtime=None)
        result = await router.dispatch(ctx)
        assert 'No active agent' in result.content


class TestCompact:
    @pytest.mark.asyncio
    async def test_no_messages(self):
        router = make_router()
        ctx = make_ctx('/compact', runtime=MockRuntime())
        ctx.extra['messages'] = None
        result = await router.dispatch(ctx)
        assert 'No messages' in result.content

    @pytest.mark.asyncio
    async def test_with_messages_no_session_module(self):
        msgs = [Message(role='system', content='hi'), Message(role='user', content='test')]
        router = make_router()
        ctx = make_ctx('/compact', runtime=MockRuntime(), messages=msgs)
        result = await router.dispatch(ctx)
        # Should gracefully handle missing PR#912 module
        assert result is not None
        assert result.type == CommandResultType.MESSAGE

    @pytest.mark.asyncio
    async def test_alias_compress(self):
        msgs = [Message(role='system', content='hi')]
        router = make_router()
        ctx = make_ctx('/compress', runtime=MockRuntime(), messages=msgs)
        result = await router.dispatch(ctx)
        assert result is not None


class TestContext:
    @pytest.fixture(autouse=True)
    def _save_restore_tokens(self):
        from ms_agent.agent.llm_agent import LLMAgent
        saved = (
            LLMAgent.LAST_PROMPT_TOKENS,
            LLMAgent.LAST_COMPLETION_TOKENS,
            LLMAgent.LAST_REASONING_TOKENS,
        )
        yield
        (
            LLMAgent.LAST_PROMPT_TOKENS,
            LLMAgent.LAST_COMPLETION_TOKENS,
            LLMAgent.LAST_REASONING_TOKENS,
        ) = saved

    @pytest.mark.asyncio
    async def test_shows_context_usage_with_known_model(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.LAST_PROMPT_TOKENS = 10000
        LLMAgent.LAST_COMPLETION_TOKENS = 2000
        LLMAgent.LAST_REASONING_TOKENS = 0
        msgs = [
            Message(role='system', content='You are helpful.'),
            Message(role='user', content='hello'),
            Message(role='assistant', content='hi there'),
            Message(role='user', content='bye'),
        ]
        router = make_router()
        ctx = make_ctx('/context', runtime=MockRuntime(), messages=msgs)
        result = await router.dispatch(ctx)
        assert '12,000' in result.content
        assert '131,072' in result.content
        assert '%' in result.content
        assert 'Prompt:' in result.content
        assert 'Messages:' in result.content

    @pytest.mark.asyncio
    async def test_shows_reasoning_tokens(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.LAST_PROMPT_TOKENS = 5000
        LLMAgent.LAST_COMPLETION_TOKENS = 3000
        LLMAgent.LAST_REASONING_TOKENS = 2500
        router = make_router()
        ctx = make_ctx('/context', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'Thinking: 2,500' in result.content

    @pytest.mark.asyncio
    async def test_unknown_model_no_percentage(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.LAST_PROMPT_TOKENS = 100
        LLMAgent.LAST_COMPLETION_TOKENS = 50
        runtime = MockRuntime()
        runtime.llm.model = 'some-unknown-model-xyz'
        router = make_router()
        ctx = make_ctx('/context', runtime=runtime)
        result = await router.dispatch(ctx)
        assert 'unknown' in result.content.lower()
        assert '%' not in result.content

    @pytest.mark.asyncio
    async def test_no_api_calls_yet(self):
        from ms_agent.agent.llm_agent import LLMAgent
        LLMAgent.LAST_PROMPT_TOKENS = 0
        LLMAgent.LAST_COMPLETION_TOKENS = 0
        router = make_router()
        ctx = make_ctx('/context', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert result is not None
        assert '0' in result.content


class TestAllCommandsRegistered:
    def test_help_lists_new_commands(self):
        router = make_router()
        cmds = router.list_commands('cli')
        all_names = []
        for cat_cmds in cmds.values():
            all_names.extend(c.name for c in cat_cmds)
        assert 'usage' in all_names
        assert 'model' in all_names
        assert 'config' in all_names
        assert 'quit' in all_names
        assert 'tools' in all_names
        assert 'compact' in all_names
        assert 'context' in all_names
        assert 'mcp' in all_names
        assert 'skills' in all_names
        assert 'search' in all_names
        assert 'instruction' in all_names
        assert 'profile' in all_names
        assert 'memory' in all_names

    def test_total_builtin_count(self):
        router = make_router()
        cmds = router.list_commands('cli')
        total = sum(len(v) for v in cmds.values())
        assert total == 18


class TestModelProbe:
    @pytest.fixture(autouse=True)
    def _isolate_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv('MS_AGENT_HOME', str(tmp_path / 'ms_home'))
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    @pytest.mark.asyncio
    async def test_auth_rolls_back_the_new_key(self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('auth', 401, []))
        _keyed('acme')
        result = await make_router().dispatch(
            make_ctx('/model provider key acme sk-new', runtime=MockRuntime()))
        assert '没有换成它' in result.content
        assert '可复制' in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['api_key'] == 'sk-test'

    @pytest.mark.asyncio
    async def test_url_change_does_not_send_the_saved_key(
            self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        calls = []

        def spy(url, protocol, api_key):
            calls.append((url, protocol, api_key))
            return CatalogProbe('ok', 200, ['m'])

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog', spy)
        _keyed('acme')
        calls.clear()
        result = await make_router().dispatch(
            make_ctx(
                '/model provider url acme https://other.example/v1',
                runtime=MockRuntime()))
        assert calls == []
        assert 'Saved base URL for acme.' in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['base_url'] == (
            'https://other.example/v1')
        assert data['providers']['acme']['api_key'] == 'sk-test'

    @pytest.mark.asyncio
    async def test_set_url_only_does_not_probe(self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        calls = []

        def spy(url, protocol, api_key):
            calls.append(api_key)
            return CatalogProbe('ok', 200, ['m'])

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog', spy)
        _keyed('acme')
        calls.clear()
        await make_router().dispatch(
            make_ctx(
                '/model provider set acme url=https://set.example/v1',
                runtime=MockRuntime()))
        assert calls == []
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['base_url'] == 'https://set.example/v1'
        assert data['providers']['acme']['api_key'] == 'sk-test'

    @pytest.mark.asyncio
    async def test_new_key_is_sent_only_to_the_saved_url(
            self, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        calls = []

        def spy(url, protocol, api_key):
            calls.append((url, api_key))
            return CatalogProbe('ok', 200, ['m'])

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog', spy)
        _keyed('acme')
        calls.clear()
        await make_router().dispatch(
            make_ctx(
                '/model provider key acme sk-new-key', runtime=MockRuntime()))
        assert calls == [('https://example.invalid/v1', 'sk-new-key')]

    @pytest.mark.asyncio
    async def test_unreachable_keeps_the_new_key(self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('unreachable', None, []))
        _keyed('acme')
        result = await make_router().dispatch(
            make_ctx(
                '/model provider key acme sk-offline', runtime=MockRuntime()))
        assert 'Saved API key for acme.' in result.content
        assert '这个地址现在连不上，密钥还没向供应商确认。' in result.content
        assert '没有保存' not in result.content
        assert '没有换成它' not in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['api_key'] == 'sk-offline'

    @pytest.mark.asyncio
    async def test_unreachable_keeps_a_key_and_url_written_together(
            self, tmp_path, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        calls = []

        def spy(url, protocol, api_key):
            calls.append((url, api_key))
            return CatalogProbe('unreachable', None, [])

        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog', spy)
        result = await make_router().dispatch(
            make_ctx(
                '/model provider add gate '
                'key=sk-together url=https://gate.example/v1',
                runtime=MockRuntime()))
        assert calls == [('https://gate.example/v1', 'sk-together')]
        assert '这个地址现在连不上，密钥还没向供应商确认。' in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['gate']['api_key'] == 'sk-together'
        assert data['providers']['gate']['base_url'] == 'https://gate.example/v1'

    @pytest.mark.asyncio
    async def test_clear_key_does_not_claim_it_applied(self, tmp_path):
        _keyed('acme')
        result = await make_router().dispatch(
            make_ctx(
                '/model provider key acme clear', runtime=MockRuntime()))
        assert result.content.startswith('已清除 acme 的密钥。')
        assert '已生效' not in result.content
        assert 'Live credentials' not in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert 'api_key' not in data['providers']['acme']

    @pytest.mark.asyncio
    async def test_clear_live_key_rearms_the_setup_notice(self, tmp_path):
        import ms_agent.agent.llm_agent as mod
        _keyed('openai')
        mod._credential_notice_sent = True
        try:
            result = await make_router().dispatch(
                make_ctx(
                    '/model provider key openai clear', runtime=MockRuntime()))
            assert result.content == '已清除 openai 的密钥。'
            assert mod._credential_notice_sent is False
        finally:
            mod._credential_notice_sent = False
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert 'api_key' not in data['providers']['openai']

    @pytest.mark.asyncio
    async def test_missing_id_does_not_change_the_default(self, monkeypatch):
        _keyed('openai')
        _catalog_ok(monkeypatch, ['qwen-plus', 'qwen-max'])
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model gpt-4o', runtime=runtime))
        assert result.type == CommandResultType.MESSAGE
        assert '没有改默认模型' in result.content
        assert 'qwen-plus' in result.content
        assert runtime.llm.model == 'qwen3.7-plus'

    @pytest.mark.asyncio
    async def test_no_catalog_still_saves(self, monkeypatch):
        from ms_agent.llm.model_discovery import CatalogProbe
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        monkeypatch.setattr(
            'ms_agent.llm.model_discovery.probe_model_catalog',
            lambda *_a, **_k: CatalogProbe('no_catalog', 404, []))
        _keyed('openai')
        runtime = MockRuntime()
        result = await make_router().dispatch(
            make_ctx('/model gpt-4o', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert '没有返回模型列表' in result.content
        assert runtime.llm.model == 'gpt-4o'
        assert ModelSettingsManager(global_home()).get_default_model() == (
            'openai/gpt-4o')

    @pytest.mark.asyncio
    async def test_model_list_names_non_chat_models(self):
        from ms_agent.llm.model_discovery import LIST_FOOTER
        result = await make_router().dispatch(
            make_ctx('/model list', runtime=MockRuntime()))
        assert LIST_FOOTER in result.content
