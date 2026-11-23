"""Helpers for TUI / WebUI ledger e2e tests (imported by tests, not conftest)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from omegaconf import OmegaConf

from ms_agent.command.builtin import register_builtin_commands
from ms_agent.command.router import CommandRouter
from ms_agent.command.types import CommandContext


def make_router() -> CommandRouter:
    router = CommandRouter()
    register_builtin_commands(router)
    return router


def make_ctx(text: str, runtime=None) -> CommandContext:
    router = make_router()
    cmd, args = CommandRouter.parse_input(text)
    return CommandContext(
        raw_input=text,
        command_name=cmd,
        args=args,
        source='tui',
        runtime=runtime,
        extra={'router': router},
    )


async def slash(text: str, runtime=None):
    ctx = make_ctx(text, runtime)
    return await ctx.extra['router'].dispatch(ctx)


def run_slash(text: str, runtime=None):
    """Sync wrapper so e2e tests do not require pytest-asyncio."""
    return asyncio.run(slash(text, runtime))


def runtime_for(work: Path):
    return SimpleNamespace(
        config=OmegaConf.create({'output_dir': str(work)}),
        tool_manager=None,
        _skill_runtime=None,
        memory_tools=[],
        llm=None,
    )


@dataclass
class DummyLLM:
    config: object
    model: str = ''

    def __post_init__(self):
        if not self.model:
            self.model = str(
                OmegaConf.select(self.config, 'llm.model', default='') or '')


@dataclass
class ModelRuntime:
    work: Path
    model: str = 'qwen3.7-plus'
    service: str = 'openai'
    api_key: str = 'sk-test-not-real'
    memory_tools: list = field(default_factory=list)
    tool_manager: object = None
    _skill_runtime: object = None

    def __post_init__(self):
        self.config = OmegaConf.create({
            'output_dir': str(self.work),
            'llm': {
                'service': self.service,
                'model': self.model,
                'openai_api_key': self.api_key,
                'use_provider_router': True,
            },
        })
        self.llm = DummyLLM(self.config, self.model)

    async def load_memory(self):
        self.memory_tools.append('loaded')
