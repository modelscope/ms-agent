"""Bridge between SkillCatalog and the slash command system.

Registers as an interceptor (lowest priority tier) in CommandRouter.
Disabled skills can still be triggered via / (per meeting decision).

Match logic: skill_id (directory name) first, then frontmatter name.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext, CommandResult, CommandResultType

if TYPE_CHECKING:
    from ms_agent.skill.catalog import SkillCatalog
    from ms_agent.skill.schema import SkillSchema

_FRONTMATTER_RE = re.compile(r'^---\s*\n.*?\n---\s*\n', re.DOTALL)


class SkillCommandBridge:

    def __init__(self, catalog: 'SkillCatalog') -> None:
        self._catalog = catalog

    def register(self, router: CommandRouter) -> None:
        router.register_interceptor(self._intercept)

    def _find_skill(self, name: str) -> 'SkillSchema | None':
        skill = self._catalog.get_skill(name)
        if skill:
            return skill
        for skill in self._catalog._skills.values():
            if skill.name.lower() == name.lower():
                return skill
        return None

    async def _intercept(self, ctx: CommandContext) -> CommandResult | None:
        skill = self._find_skill(ctx.command_name)
        if skill is None:
            return None

        if not ctx.args:
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=(
                    f'Skill: {skill.name}\n'
                    f'Description: {skill.description}\n'
                    f'Usage: /{skill.skill_id} <your instruction>'
                ),
            )

        body = _strip_frontmatter(skill.content)
        body = body.replace('$ARGUMENTS', ctx.args)

        enriched = (
            f'Use the [{skill.name}] skill located at `{skill.skill_path}`.\n\n'
            f'{body}\n\n'
            f"User's request: {ctx.args}"
        )
        return CommandResult(
            type=CommandResultType.SUBMIT_PROMPT,
            content=enriched,
        )


def _strip_frontmatter(content: str) -> str:
    return _FRONTMATTER_RE.sub('', content, count=1).strip()
