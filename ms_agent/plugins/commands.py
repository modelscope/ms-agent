from __future__ import annotations

import re
from pathlib import Path

from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef as RouterCommandDef,
    CommandResult,
    CommandResultType,
)
from ms_agent.plugins.types import CommandDef

_FRONTMATTER_RE = re.compile(r'^---\s*\n.*?\n---\s*\n', re.DOTALL)


def register_plugin_commands(
    router: CommandRouter,
    command_defs: list[CommandDef],
) -> None:
    """Register plugin commands as slash commands.

    The namespaced form (`/<plugin-id>:<command>`) is always registered. The
    unqualified form is registered only when it does not conflict with an
    existing command.
    """
    for cmd in command_defs:
        namespaced = f'{cmd.plugin_id}:{cmd.name}'
        router.register(
            RouterCommandDef(
                name=namespaced,
                description=cmd.description or f'Plugin command {namespaced}',
                category=f'plugin:{cmd.plugin_id}',
            ),
            _handler_for(cmd),
        )
        if router.resolve(cmd.name) is None:
            router.register(
                RouterCommandDef(
                    name=cmd.name,
                    description=cmd.description or f'Plugin command {cmd.name}',
                    category=f'plugin:{cmd.plugin_id}',
                ),
                _handler_for(cmd),
            )


def _handler_for(cmd: CommandDef):
    async def _handler(ctx: CommandContext) -> CommandResult:
        try:
            content = Path(cmd.path).read_text(encoding='utf-8')
        except OSError as exc:
            return CommandResult(
                type=CommandResultType.MESSAGE,
                content=f'Plugin command `{cmd.plugin_id}:{cmd.name}` failed: {exc}',
            )
        body = _strip_frontmatter(content)
        args = ctx.args or ''
        body = body.replace('$ARGUMENTS', args).replace('${ARGUMENTS}', args)
        prompt = (
            f'Run plugin command `/{cmd.plugin_id}:{cmd.name}` from `{cmd.path}`.\n\n'
            f'{body}'
        )
        if args and '$ARGUMENTS' not in content and '${ARGUMENTS}' not in content:
            prompt = f'{prompt}\n\nUser arguments: {args}'
        return CommandResult(
            type=CommandResultType.SUBMIT_PROMPT,
            content=prompt,
            metadata={'plugin_id': cmd.plugin_id, 'command': cmd.name},
        )

    return _handler


def _strip_frontmatter(content: str) -> str:
    return _FRONTMATTER_RE.sub('', content, count=1).strip()
