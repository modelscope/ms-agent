from ms_agent.command.router import CommandRouter
from ms_agent.command.types import (
    CommandContext,
    CommandDef,
    CommandResult,
    CommandResultType,
)

CMD_USAGE = CommandDef(
    name='usage',
    description='Show token usage statistics',
    category='info',
    aliases=('stats',),
)

CMD_QUIT = CommandDef(
    name='quit',
    description='Exit the interactive session',
    category='session',
    aliases=('exit',),
)

CMD_TOOLS = CommandDef(
    name='tools',
    description='List configured tools',
    category='info',
)

CMD_COMPACT = CommandDef(
    name='compact',
    description='Compress conversation context',
    category='context',
    aliases=('compress',),
)

CMD_CONTEXT = CommandDef(
    name='context',
    description='Show context window statistics',
    category='info',
)


async def cmd_usage(ctx: CommandContext) -> CommandResult:
    from ms_agent.agent.llm_agent import LLMAgent

    prompt = LLMAgent.TOTAL_PROMPT_TOKENS
    completion = LLMAgent.TOTAL_COMPLETION_TOKENS
    reasoning = LLMAgent.TOTAL_REASONING_TOKENS
    lines = [
        f'Prompt tokens:     {prompt:,}',
        f'Completion tokens: {completion:,}',
        f'Total:             {prompt + completion:,}',
    ]
    if reasoning:
        lines.append(f'  Reasoning:       {reasoning:,}')
    if LLMAgent.TOTAL_CACHED_TOKENS:
        lines.append(f'Cache hit:         {LLMAgent.TOTAL_CACHED_TOKENS:,}')
    if LLMAgent.TOTAL_CACHE_CREATION_INPUT_TOKENS:
        lines.append(
            f'Cache created:     {LLMAgent.TOTAL_CACHE_CREATION_INPUT_TOKENS:,}'
        )
    if ctx.runtime:
        lines.append(f'Rounds:            {ctx.runtime.round}')
    return CommandResult(type=CommandResultType.MESSAGE, content='\n'.join(lines))


async def cmd_quit(ctx: CommandContext) -> CommandResult:
    if ctx.runtime:
        ctx.runtime.should_stop = True
    return CommandResult(type=CommandResultType.QUIT, content='Goodbye.')


def _is_tool_entry(tools_config, key: str) -> bool:
    if key.startswith('_'):
        return False
    from omegaconf import DictConfig
    val = tools_config[key]
    return isinstance(val, (dict, DictConfig))


async def cmd_tools(ctx: CommandContext) -> CommandResult:
    if not ctx.runtime or not ctx.runtime.llm:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No active agent.'
        )

    config = ctx.runtime.llm.config
    tools_config = getattr(config, 'tools', None)
    if not tools_config:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No tools configured.'
        )

    tool_names = [k for k in tools_config if _is_tool_entry(tools_config, k)]
    if not tool_names:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No tools configured.'
        )

    lines = [f'Configured tools ({len(tool_names)}):']
    for name in sorted(tool_names):
        lines.append(f'  • {name}')
    return CommandResult(type=CommandResultType.MESSAGE, content='\n'.join(lines))


async def cmd_compact(ctx: CommandContext) -> CommandResult:
    messages = ctx.extra.get('messages')
    if not messages:
        return CommandResult(
            type=CommandResultType.MESSAGE, content='No messages available.'
        )

    try:
        from ms_agent.session.context_assembler import ContextAssembler  # noqa: F401
    except ImportError:
        return CommandResult(
            type=CommandResultType.MESSAGE,
            content=(
                'Context compaction not available yet.'
            ),
        )

    return CommandResult(
        type=CommandResultType.MESSAGE,
        content=(
            f'Compaction requested. Current message count: {len(messages)}.\n'
            f'(Full implementation available after PR#912 merge)'
        ),
    )


MODEL_CONTEXT_WINDOWS = {
    'qwen3-235b-a22b': 131072,
    'qwen3-32b': 131072,
    'qwen3-30b-a3b': 131072,
    'qwen3-14b': 131072,
    'qwen3-8b': 131072,
    'qwen3-4b': 131072,
    'qwen3-1.7b': 32768,
    'qwen3-0.6b': 32768,
    'qwq-32b': 131072,
    'qwen-plus': 131072,
    'qwen-plus-latest': 131072,
    'qwen-turbo': 1000000,
    'qwen-turbo-latest': 1000000,
    'qwen-max': 131072,
    'qwen-max-latest': 131072,
    'qwen-long': 10000000,
    'qwen3.7-plus': 131072,
    'qwen3.5-plus': 131072,
    'gpt-4o': 128000,
    'gpt-4o-mini': 128000,
    'gpt-4-turbo': 128000,
    'gpt-4': 8192,
    'gpt-3.5-turbo': 16385,
    'o1': 200000,
    'o1-mini': 128000,
    'o1-pro': 200000,
    'o3': 200000,
    'o3-mini': 200000,
    'o4-mini': 200000,
    'claude-sonnet-4-5-20250514': 200000,
    'claude-opus-4-0-20250514': 200000,
    'claude-3-5-sonnet-20241022': 200000,
    'claude-3-5-haiku-20241022': 200000,
    'deepseek-chat': 65536,
    'deepseek-reasoner': 65536,
}


def _lookup_context_window(model: str) -> int | None:
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if key in model or model in key:
            return size
    return None


async def cmd_context(ctx: CommandContext) -> CommandResult:
    from ms_agent.agent.llm_agent import LLMAgent

    last_prompt = LLMAgent.LAST_PROMPT_TOKENS
    last_completion = LLMAgent.LAST_COMPLETION_TOKENS
    last_reasoning = LLMAgent.LAST_REASONING_TOKENS
    used = last_prompt + last_completion

    model = ''
    context_window = None
    if ctx.runtime and ctx.runtime.llm:
        model = ctx.runtime.llm.model or ''
        context_window = _lookup_context_window(model)

    lines = []
    if context_window:
        pct = used / context_window * 100 if context_window else 0
        bar_len = 20
        filled = round(pct / 100 * bar_len)
        bar = '█' * filled + '░' * (bar_len - filled)
        lines.append(f'Context: [{bar}] {pct:.1f}%')
        lines.append(
            f'  Used:     {used:,} / {context_window:,} tokens'
        )
    else:
        lines.append(f'Context used: {used:,} tokens')
        if model:
            lines.append(f'  (window size unknown for "{model}")')

    lines.append(f'  Prompt:   {last_prompt:,}')
    lines.append(f'  Response: {last_completion:,}')
    if last_reasoning:
        lines.append(f'  Thinking: {last_reasoning:,}')

    messages = ctx.extra.get('messages')
    if messages:
        msg_count = len(messages)
        user_msgs = sum(1 for m in messages if m.role == 'user')
        assistant_msgs = sum(1 for m in messages if m.role == 'assistant')
        tool_msgs = sum(1 for m in messages if m.role == 'tool')
        lines.append(f'Messages:   {msg_count} (user:{user_msgs} asst:{assistant_msgs} tool:{tool_msgs})')

    return CommandResult(type=CommandResultType.MESSAGE, content='\n'.join(lines))


def register_context_commands(router: CommandRouter) -> None:
    router.register(CMD_USAGE, cmd_usage)
    router.register(CMD_QUIT, cmd_quit)
    router.register(CMD_TOOLS, cmd_tools)
    router.register(CMD_COMPACT, cmd_compact)
    router.register(CMD_CONTEXT, cmd_context)
