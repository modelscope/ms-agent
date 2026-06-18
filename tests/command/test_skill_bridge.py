import pytest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from ms_agent.command.router import CommandRouter
from ms_agent.command.skill_bridge import SkillCommandBridge
from ms_agent.command.types import CommandContext, CommandResultType


@dataclass
class MockSkill:
    skill_id: str = 'test-skill'
    name: str = 'Test Skill'
    description: str = 'A test skill for unit tests'
    content: str = '---\nname: Test Skill\ndescription: A test\n---\nDo $ARGUMENTS carefully.'
    skill_path: Path = field(default_factory=lambda: Path('/mock/skills/test-skill'))
    tags: List[str] = field(default_factory=list)


class MockCatalog:
    def __init__(self, skills=None):
        self._skills = {s.skill_id: s for s in (skills or [])}

    def get_skill(self, skill_id):
        return self._skills.get(skill_id)


def _make_ctx(text: str) -> CommandContext:
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(raw_input=text, command_name=cmd, args=args)


class TestSkillCommandBridge:
    @pytest.fixture
    def skill(self):
        return MockSkill()

    @pytest.fixture
    def catalog(self, skill):
        return MockCatalog(skills=[skill])

    @pytest.fixture
    def router(self, catalog):
        r = CommandRouter()
        bridge = SkillCommandBridge(catalog)
        bridge.register(r)
        return r

    @pytest.mark.asyncio
    async def test_no_args_returns_info(self, router, skill):
        ctx = _make_ctx(f'/{skill.skill_id}')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.type == CommandResultType.MESSAGE
        assert skill.name in result.content
        assert skill.description in result.content

    @pytest.mark.asyncio
    async def test_with_args_returns_submit_prompt(self, router, skill):
        ctx = _make_ctx(f'/{skill.skill_id} translate this')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.type == CommandResultType.SUBMIT_PROMPT
        assert 'translate this' in result.content
        assert skill.name in result.content

    @pytest.mark.asyncio
    async def test_arguments_substituted(self, router, skill):
        ctx = _make_ctx(f'/{skill.skill_id} my task')
        result = await router.dispatch(ctx)
        assert 'Do my task carefully.' in result.content

    @pytest.mark.asyncio
    async def test_frontmatter_stripped(self, router, skill):
        ctx = _make_ctx(f'/{skill.skill_id} something')
        result = await router.dispatch(ctx)
        assert '---' not in result.content
        assert 'name: Test Skill' not in result.content

    @pytest.mark.asyncio
    async def test_unknown_skill_returns_none(self, router):
        ctx = _make_ctx('/nonexistent-skill do stuff')
        result = await router.dispatch(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_match_by_frontmatter_name(self):
        skill = MockSkill(skill_id='my-dir-name', name='fancy-name')
        catalog = MockCatalog(skills=[skill])
        router = CommandRouter()
        SkillCommandBridge(catalog).register(router)

        ctx = _make_ctx('/fancy-name do stuff')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.type == CommandResultType.SUBMIT_PROMPT

    @pytest.mark.asyncio
    async def test_disabled_skill_still_works(self):
        skill = MockSkill()
        catalog = MockCatalog(skills=[skill])
        router = CommandRouter()
        SkillCommandBridge(catalog).register(router)

        ctx = _make_ctx(f'/{skill.skill_id} do it')
        result = await router.dispatch(ctx)
        assert result is not None
        assert result.type == CommandResultType.SUBMIT_PROMPT

    @pytest.mark.asyncio
    async def test_builtin_takes_precedence_over_skill(self):
        from ms_agent.command.builtin import register_builtin_commands

        skill = MockSkill(skill_id='help', name='help')
        catalog = MockCatalog(skills=[skill])
        router = CommandRouter()
        register_builtin_commands(router)
        SkillCommandBridge(catalog).register(router)

        cmd, args = CommandRouter.parse_input('/help')
        ctx = CommandContext(
            raw_input='/help',
            command_name=cmd,
            args=args,
            extra={'router': router},
        )
        result = await router.dispatch(ctx)
        assert result is not None
        assert 'Available commands' in result.content
