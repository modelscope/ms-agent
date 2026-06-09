from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


class CommandResultType(str, Enum):
    MESSAGE = 'message'
    SUBMIT_PROMPT = 'submit'
    MUTATE_STATE = 'mutate'
    QUIT = 'quit'


@dataclass(frozen=True)
class CommandResult:
    type: CommandResultType
    content: str = ''
    metadata: dict = field(default_factory=dict)


@dataclass
class CommandContext:
    raw_input: str
    command_name: str
    args: str = ''
    source: str = 'cli'
    runtime: Any = None
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CommandDef:
    name: str
    description: str
    category: str = 'general'
    priority: int = 20
    aliases: tuple[str, ...] = ()
    ui_scope: frozenset[str] = frozenset({'cli', 'tui', 'webui'})


CommandHandler = Callable[[CommandContext], Awaitable[Optional[CommandResult]]]
