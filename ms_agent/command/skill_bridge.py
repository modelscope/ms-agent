"""Bridge between SkillCatalog and the slash command system.

Registers as an interceptor (lowest priority tier) in CommandRouter.
Disabled skills can still be triggered via / (per meeting decision).

Match logic: skill_id (directory name) first, then frontmatter name.

Besides the interactive interceptor path, two public helpers expose the same
expansion semantics to non-interactive surfaces (WebUI backend, future TUI):

- ``expand_skill(catalog, name_or_id, args)`` — structured invocation: the
  caller already knows which skill the user picked (e.g. a composer dropdown
  sent the skill id alongside the message).
- ``expand_slash_text(catalog, text)`` — free-text invocation: find the first
  whitespace-delimited ``/token`` anywhere in the text (Claude-Code-style
  boundary rule, not just line start), gate it against the catalog, and expand
  with the rest of the text as the arguments. Unknown ``/x`` tokens fall
  through (return None) so ordinary prose is never hijacked.
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
# A slash token: "/" + a word (letters/digits/_/-/.), delimited by whitespace
# or string boundaries on both sides. Mid-word slashes (a/b, http://…) never
# match; whether a matching token IS a command is decided by the catalog gate.
_SLASH_TOKEN_RE = re.compile(r'(?:(?<=\s)|^)/([A-Za-z0-9][\w.-]*)(?=\s|$)')


def find_skill(catalog: 'SkillCatalog', name: str) -> 'SkillSchema | None':
    """Resolve a skill by skill_id (exact) then frontmatter name (case-insensitive)."""
    skill = catalog.get_skill(name)
    if skill:
        return skill
    for skill in catalog._skills.values():
        if skill.name.lower() == name.lower():
            return skill
    return None


def expand_skill(catalog: 'SkillCatalog', name_or_id: str,
                 args: str) -> CommandResult | None:
    """Expand one known-skill invocation into a CommandResult.

    Returns None when the skill doesn't exist; a usage MESSAGE when ``args``
    is empty; else a SUBMIT_PROMPT whose content is the skill body (frontmatter
    stripped, ``$ARGUMENTS`` substituted) wrapped with the standard preamble.
    Surface-agnostic: no router/context state is involved.
    """
    skill = find_skill(catalog, name_or_id)
    if skill is None:
        return None

    if not args:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=(
                f'Skill: {skill.name}\n'
                f'Description: {skill.description}\n'
                f'Usage: /{skill.skill_id} <your instruction>'
            ),
        )

    body = _strip_frontmatter(skill.content)
    body = body.replace('$ARGUMENTS', args)

    enriched = (
        f'Use the [{skill.name}] skill located at `{skill.skill_path}`.\n\n'
        f'{body}\n\n'
        f"User's request: {args}"
    )
    return CommandResult(
        type=CommandResultType.SUBMIT_PROMPT,
        content=enriched,
    )


def expand_slash_text(catalog: 'SkillCatalog',
                      text: str) -> CommandResult | None:
    """Expand the first catalog-known ``/token`` found anywhere in ``text``.

    Tokens must be whitespace-delimited (or at the string boundaries); the
    FIRST token that resolves to a real skill wins and the arguments are the
    whole text with that token removed (so a mid-sentence invocation keeps the
    surrounding words as the request). Tokens that don't match any skill are
    left alone — the text falls through as an ordinary message (None).
    """
    for match in _SLASH_TOKEN_RE.finditer(text):
        skill = find_skill(catalog, match.group(1))
        if skill is None:
            continue
        # Drop the token and mend the seam (collapse doubled spaces/tabs only —
        # newlines and the rest of the text stay untouched).
        args = re.sub(r'[ \t]{2,}', ' ',
                      text[:match.start()] + text[match.end():]).strip()
        return expand_skill(catalog, match.group(1), args)
    return None


class SkillCommandBridge:

    def __init__(self, catalog: 'SkillCatalog') -> None:
        self._catalog = catalog

    def register(self, router: CommandRouter) -> None:
        router.register_interceptor(self._intercept)

    def _find_skill(self, name: str) -> 'SkillSchema | None':
        return find_skill(self._catalog, name)

    async def _intercept(self, ctx: CommandContext) -> CommandResult | None:
        return expand_skill(self._catalog, ctx.command_name, ctx.args)


def _strip_frontmatter(content: str) -> str:
    return _FRONTMATTER_RE.sub('', content, count=1).strip()
