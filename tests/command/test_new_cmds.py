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

    @pytest.mark.asyncio
    async def test_show_current_model(self):
        router = make_router()
        ctx = make_ctx('/model', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'qwen3.7-plus' in result.content
        assert 'openai' in result.content

    @pytest.mark.asyncio
    async def test_switch_model(self):
        from unittest.mock import patch
        runtime = MockRuntime()
        router = make_router()

        class Rebuilt:
            def __init__(self):
                self.config = runtime.llm.config
                self.model = 'gpt-4o'

        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(
                make_ctx('/model gpt-4o', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'gpt-4o' in result.content
        assert runtime.llm.model == 'gpt-4o'

    @pytest.mark.asyncio
    async def test_slash_in_model_id_stays_on_current_provider(self):
        from unittest.mock import patch
        runtime = MockRuntime()
        router = make_router()

        class Rebuilt:
            def __init__(self):
                self.config = runtime.llm.config
                self.model = 'MiniMax/MiniMax-M2.1'

        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(
                make_ctx('/model MiniMax/MiniMax-M2.1', runtime=runtime))
        assert result.type == CommandResultType.MUTATE_STATE
        assert runtime.llm.model == 'MiniMax/MiniMax-M2.1'
        assert runtime.llm.config.llm.service == 'openai'
        assert 'Provider: openai' in result.content
        assert 'Model:    MiniMax/MiniMax-M2.1' in result.content

    @pytest.mark.asyncio
    async def test_known_provider_then_slashy_model(self):
        from unittest.mock import patch
        runtime = MockRuntime()
        router = make_router()

        class Rebuilt:
            def __init__(self):
                self.config = runtime.llm.config
                self.model = 'MiniMax/MiniMax-M2.1'
                self.spec = type('S', (), {'name': 'dashscope'})()
                self.transport = type('T', (), {'base_url': 'https://ds'})()

        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(
                make_ctx(
                    '/model dashscope/MiniMax/MiniMax-M2.1', runtime=runtime))
        assert runtime.llm.config.llm.service == 'dashscope'
        assert runtime.llm.model == 'MiniMax/MiniMax-M2.1'
        assert 'Provider: dashscope' in result.content
        assert 'Switch:   /model dashscope MiniMax/MiniMax-M2.1' in result.content

    @pytest.mark.asyncio
    async def test_space_form_sets_provider_when_model_has_slash(self):
        from unittest.mock import patch
        runtime = MockRuntime()

        class Rebuilt:
            def __init__(self):
                self.config = runtime.llm.config
                self.model = 'MiniMax/MiniMax-M2.1'

        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
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
            make_ctx('/model minimax/MiniMax-M2.1', runtime=runtime))
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
        runtime = MockRuntime()
        router = make_router()
        await router.dispatch(
            make_ctx(
                '/model provider add acme key=sk url=https://acme/v1 protocol=openai',
                runtime=runtime))
        result = await router.dispatch(
            make_ctx('/model minimax/MiniMax-M2.1', runtime=runtime))
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
        assert 'minimax MiniMax-M2.1' not in result.content
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
    async def test_switch_model_replaces_setup_stub(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        config = _make_mock_config()
        stub = SimpleNamespace(config=config, model='old', _setup_stub=True)
        runtime = MockRuntime(llm=stub)
        router = make_router()
        ctx = make_ctx('/model dashscope/qwen3.8-flash', runtime=runtime)

        class Rebuilt:
            def __init__(self):
                self.config = config
                self.model = 'qwen3.8-flash'

        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'qwen3.8-flash' in result.content
        assert runtime.llm.model == 'qwen3.8-flash'
        assert config.llm.service == 'dashscope'

    @pytest.mark.asyncio
    async def test_switch_model_persists_to_settings_not_project_patch(self, tmp_path):
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

        class Rebuilt:
            def __init__(self):
                self.config = config
                self.model = 'qwen3.7-max'

        from unittest.mock import patch
        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(ctx)

        assert result.type == CommandResultType.MUTATE_STATE
        assert 'Saved as the default' in result.content
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
    async def test_switch_model_no_source_file(self, tmp_path):
        # Still writes the WebUI-shared default_model in settings.json.
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/model gpt-4o', runtime=runtime)

        class Rebuilt:
            def __init__(self):
                self.config = runtime.llm.config
                self.model = 'gpt-4o'

        from unittest.mock import patch
        with patch('ms_agent.llm.LLM.from_config', return_value=Rebuilt()):
            result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'Saved as the default' in result.content
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        assert ModelSettingsManager(global_home()).get_default_model() == 'openai/gpt-4o'

    @pytest.mark.asyncio
    async def test_model_list_reads_settings(self, tmp_path):
        from ms_agent.config.model_settings import ModelSettingsManager
        from ms_agent.project.paths import global_home
        ModelSettingsManager(global_home()).set_default_model(
            'a-1', provider='acme')
        router = make_router()
        ctx = make_ctx('/model list', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'Default: acme/a-1' in result.content
        assert 'same as WebUI' in result.content

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
        assert 'dropped 2' in result.content
        data = json.loads((tmp_path / 'ms_home' / 'settings.json').read_text())
        assert data['providers']['acme']['models'] == ['catalog-only']

        skipped = await router.dispatch(
            make_ctx('/model list live openai', runtime=runtime))
        assert 'skipped (no API key)' in skipped.content

    @pytest.mark.asyncio
    async def test_provider_add_set_key_catalog(self, tmp_path):
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
        assert 'key=set' in listed.content
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
        assert 'Same as WebUI:' in result.content
        assert 'settings.json' in result.content
        assert 'MS_AGENT_HOME' in result.content
        assert '<provider>' in result.content
        assert 'MiniMax' not in result.content
        assert '~/.ms_agent' not in result.content
        assert '<id>' not in result.content

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
