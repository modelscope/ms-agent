"""Four-tier cascading command router.

Dispatch order: priority → exact → prefix → interceptor.
Priority commands execute outside the agent lock for instant /stop response.

Reference: nanobot/command/router.py (structure) + qwen-code (pre-parse + typed result)
"""
from __future__ import annotations

from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandHandler,
    CommandResult,
)


class CommandRouter:

    def __init__(self) -> None:
        self._priority: dict[str, CommandHandler] = {}
        self._exact: dict[str, CommandHandler] = {}
        self._prefix: list[tuple[str, CommandHandler]] = []
        self._interceptors: list[CommandHandler] = []
        self._registry: dict[str, CommandDef] = {}

    # -- registration --

    def register(self, cmd_def: CommandDef, handler: CommandHandler) -> None:
        canonical = cmd_def.name.lower()
        self._registry[canonical] = cmd_def
        target = self._priority if cmd_def.priority < 10 else self._exact
        target[canonical] = handler
        for alias in cmd_def.aliases:
            target[alias.lower()] = handler

    def register_prefix(self, prefix: str, handler: CommandHandler) -> None:
        self._prefix.append((prefix.lower(), handler))
        self._prefix.sort(key=lambda p: len(p[0]), reverse=True)

    def register_interceptor(self, handler: CommandHandler) -> None:
        self._interceptors.append(handler)

    # -- detection --

    @staticmethod
    def is_command(text: str) -> bool:
        if not text or not text.startswith('/'):
            return False
        first_word = text.split()[0]
        return '/' not in first_word[1:]

    def is_priority(self, text: str) -> bool:
        if not self.is_command(text):
            return False
        cmd, _ = self.parse_input(text)
        return cmd in self._priority

    # -- dispatch --

    async def dispatch_priority(
        self, ctx: CommandContext
    ) -> CommandResult | None:
        handler = self._priority.get(ctx.command_name.lower())
        if handler:
            return await handler(ctx)
        return None

    async def dispatch(self, ctx: CommandContext) -> CommandResult | None:
        cmd = ctx.command_name.lower()

        if handler := self._priority.get(cmd):
            return await handler(ctx)

        if handler := self._exact.get(cmd):
            return await handler(ctx)

        for pfx, handler in self._prefix:
            if cmd.startswith(pfx):
                return await handler(ctx)

        for interceptor in self._interceptors:
            result = await interceptor(ctx)
            if result is not None:
                return result

        return None

    # -- query --

    def resolve(self, name: str) -> CommandDef | None:
        clean = name.lower().lstrip('/')
        if clean in self._registry:
            return self._registry[clean]
        for cmd_def in self._registry.values():
            if clean in (a.lower() for a in cmd_def.aliases):
                return cmd_def
        return None

    def list_commands(
        self, source: str = 'cli'
    ) -> dict[str, list[CommandDef]]:
        result: dict[str, list[CommandDef]] = {}
        for cmd_def in self._registry.values():
            if source in cmd_def.ui_scope:
                result.setdefault(cmd_def.category, []).append(cmd_def)
        return result

    @staticmethod
    def parse_input(text: str) -> tuple[str, str]:
        stripped = text.strip()
        parts = stripped.split(maxsplit=1)
        cmd = parts[0].lstrip('/').lower()
        args = parts[1] if len(parts) > 1 else ''
        return cmd, args
