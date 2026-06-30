"""Tests for new builtin commands: /usage, /model, /config, /quit, /tools, /compact, /context."""
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
    @pytest.mark.asyncio
    async def test_show_current_model(self):
        router = make_router()
        ctx = make_ctx('/model', runtime=MockRuntime())
        result = await router.dispatch(ctx)
        assert 'qwen3.7-plus' in result.content
        assert 'openai' in result.content

    @pytest.mark.asyncio
    async def test_switch_model(self):
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/model gpt-4o', runtime=runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'gpt-4o' in result.content
        assert runtime.llm.model == 'gpt-4o'

    @pytest.mark.asyncio
    async def test_switch_model_persists_to_project_patch(self, tmp_path):
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
            'name': 'searcher.yaml',
        })
        runtime = MockRuntime(llm=MockLLM(model='qwen3.5-plus', config=config))
        router = make_router()
        ctx = make_ctx('/model qwen3.7-max', runtime=runtime)
        result = await router.dispatch(ctx)

        assert result.type == CommandResultType.MUTATE_STATE
        assert 'Saved to' in result.content

        # The source YAML is untouched.
        assert cfg_file.read_text(encoding='utf-8') == yaml_text

        # The override landed in the project patch, which from_task merges back.
        patch_file = tmp_path / '.ms-agent' / 'config.yaml'
        assert patch_file.exists()
        patch_cfg = OmegaConf.load(str(patch_file))
        assert patch_cfg.llm.model == 'qwen3.7-max'

    @pytest.mark.asyncio
    async def test_switch_model_no_source_file(self):
        # config without local_dir/name -> in-memory only, no crash
        runtime = MockRuntime()
        router = make_router()
        ctx = make_ctx('/model gpt-4o', runtime=runtime)
        result = await router.dispatch(ctx)
        assert result.type == CommandResultType.MUTATE_STATE
        assert 'in-memory only' in result.content

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

    def test_total_builtin_count(self):
        router = make_router()
        cmds = router.list_commands('cli')
        total = sum(len(v) for v in cmds.values())
        assert total == 12
