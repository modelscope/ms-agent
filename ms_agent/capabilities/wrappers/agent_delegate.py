# Copyright (c) ModelScope Contributors. All rights reserved.
import contextlib
import logging
import os
import sys
from copy import deepcopy
from typing import Any

from ms_agent.capabilities.async_task import AsyncTask, get_default_manager
from ms_agent.capabilities.descriptor import CapabilityDescriptor
from ms_agent.capabilities.registry import CapabilityRegistry

logger = logging.getLogger(__name__)

_manager = get_default_manager()

_DELEGATE_INPUT_PROPERTIES: dict[str, Any] = {
    'query': {
        'type': 'string',
        'description': 'The task or question for the agent to work on',
    },
    'system_prompt': {
        'type': 'string',
        'description': 'Custom system prompt for the agent (optional)',
    },
    'tools': {
        'type': 'string',
        'description': (
            'Comma-separated basic tool component names to enable, e.g. '
            '"web_search,file_system,todo_list". Alias "filesystem" is accepted '
            'for backward compatibility. Leave empty to use the default agent '
            'config tools.'
        ),
    },
    'max_rounds': {
        'type': 'integer',
        'description': 'Maximum tool-use rounds (default: 20)',
        'default': 20,
    },
    'config_path': {
        'type': 'string',
        'description': 'Path to an agent YAML config file (optional)',
    },
}

_BASIC_TOOL_DEFAULTS: dict[str, dict[str, Any]] = {
    'file_system': {
        'mcp': False,
        'include': ['write_file', 'read_file', 'list_files'],
    },
    'todo_list': {
        'mcp': False,
        'include': ['todo_write', 'todo_read'],
    },
    'web_search': {
        'mcp': False,
        'engine': 'arxiv',
    },
}

_BASIC_TOOL_ALIASES: dict[str, str] = {
    'filesystem': 'file_system',
    'file_system': 'file_system',
    'todo_list': 'todo_list',
    'web_search': 'web_search',
}

DELEGATE_TASK_DESCRIPTOR = CapabilityDescriptor(
    name='delegate_task',
    version='0.1.0',
    granularity='project',
    summary=('Delegate a task to an LLM agent that can use tools. Blocks until the agent completes.'),
    description=(
        'Creates an LLMAgent with the given configuration, runs it on the '
        'provided query, and returns the final response text.  The agent '
        'can use tools (web search, filesystem, etc.) to accomplish the '
        'task.  WARNING: this call blocks and may take minutes.'
    ),
    input_schema={
        'type': 'object',
        'properties': _DELEGATE_INPUT_PROPERTIES,
        'required': ['query'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'status': {'type': 'string'},
            'response': {'type': 'string'},
        },
    },
    tags=['agent', 'delegate', 'llm', 'sync'],
    estimated_duration='minutes',
)

SUBMIT_AGENT_TASK_DESCRIPTOR = CapabilityDescriptor(
    name='submit_agent_task',
    version='0.1.0',
    granularity='project',
    summary=('Submit an agent task to run in the background. Returns a task_id immediately.'),
    description=(
        'Starts an LLMAgent in the background and returns a task_id. '
        'Use check_agent_task(task_id) to poll progress and '
        'get_agent_result(task_id) to retrieve the final response.'
    ),
    input_schema={
        'type': 'object',
        'properties': _DELEGATE_INPUT_PROPERTIES,
        'required': ['query'],
    },
    output_schema={
        'type': 'object',
        'properties': {
            'task_id': {'type': 'string'},
            'status': {'type': 'string'},
        },
    },
    tags=['agent', 'delegate', 'llm', 'async', 'submit'],
    estimated_duration='seconds',
)

CHECK_AGENT_TASK_DESCRIPTOR = CapabilityDescriptor(
    name='check_agent_task',
    version='0.1.0',
    granularity='tool',
    summary='Check progress of a background agent task.',
    description=(
        'Polls the status of an agent task previously submitted via submit_agent_task. Returns the current status.'
    ),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description': 'The task_id returned by submit_agent_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['agent', 'delegate', 'async', 'progress'],
    estimated_duration='seconds',
)

GET_AGENT_RESULT_DESCRIPTOR = CapabilityDescriptor(
    name='get_agent_result',
    version='0.1.0',
    granularity='tool',
    summary='Get the result of a completed agent task.',
    description=(
        'Retrieves the final response from a completed agent task. '
        'If the task is still running, returns a status message.'
    ),
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description': 'The task_id returned by submit_agent_task',
            },
            'max_chars': {
                'type': 'integer',
                'description': 'Maximum characters to return (default: 50000)',
                'default': 50000,
            },
        },
        'required': ['task_id'],
    },
    tags=['agent', 'delegate', 'async', 'result'],
    estimated_duration='seconds',
)

CANCEL_AGENT_TASK_DESCRIPTOR = CapabilityDescriptor(
    name='cancel_agent_task',
    version='0.1.0',
    granularity='tool',
    summary='Cancel a running agent task.',
    description='Cancels a background agent task that is still in progress.',
    input_schema={
        'type': 'object',
        'properties': {
            'task_id': {
                'type': 'string',
                'description': 'The task_id returned by submit_agent_task',
            },
        },
        'required': ['task_id'],
    },
    tags=['agent', 'delegate', 'async', 'cancel'],
    estimated_duration='seconds',
)


def _parse_tools_str(tools_str: str | None) -> list[str] | None:
    """Parse a comma-separated tools string into a list (or None)."""
    if not tools_str:
        return None
    return [t.strip() for t in tools_str.split(',') if t.strip()]


def _build_basic_tools_config(tools_list: list[str] | None) -> dict[str, Any]:
    """Map requested basic tools to framework-compatible config entries."""
    if not tools_list:
        return {}

    tools_cfg: dict[str, Any] = {}
    for raw_name in tools_list:
        tool_name = _BASIC_TOOL_ALIASES.get(raw_name)
        if tool_name is None:
            logger.warning('Ignoring unsupported delegate tool name: %s', raw_name)
            continue
        if tool_name in tools_cfg:
            continue
        tools_cfg[tool_name] = deepcopy(_BASIC_TOOL_DEFAULTS[tool_name])
    return tools_cfg


def _build_agent_config(
    config_path: str | None = None,
    system_prompt: str | None = None,
    tools_list: list[str] | None = None,
    max_rounds: int = 20,
) -> Any:
    """Construct an OmegaConf DictConfig for :class:`LLMAgent`.

    When running as a delegate inside the MCP server, interactive callbacks
    (like ``input_callback``) are removed because stdin/stdout belong to
    the JSONRPC transport and must not be used for human I/O.
    """
    from omegaconf import DictConfig, OmegaConf

    from ms_agent.config.config import Config

    if config_path and os.path.isfile(config_path):
        config = Config.from_task(config_path)
    else:
        config = DictConfig({})

    if system_prompt:
        OmegaConf.update(config, 'prompt.system', system_prompt, merge=True)

    OmegaConf.update(config, 'max_chat_round', max_rounds, merge=True)

    # Remove interactive callbacks that read from stdin (the JSONRPC channel).
    # Must always set this key because LLMAgent.__init__ merges the default
    # agent.yaml (which contains ``callbacks: [input_callback]``) AFTER we
    # return.  OmegaConf.merge(default, ours) lets our value win.
    safe_cbs: list[str] = []
    if hasattr(config, 'callbacks') and config.callbacks:
        safe_cbs = [c for c in config.callbacks if c not in ('input_callback',)]
    OmegaConf.update(config, 'callbacks', safe_cbs, merge=False)

    OmegaConf.update(config, 'save_history', False, merge=True)

    if tools_list:
        tools_cfg = _build_basic_tools_config(tools_list)
        existing_tools = getattr(config, 'tools', DictConfig({}))
        for tool_name, tool_cfg in tools_cfg.items():
            # Preserve explicit config_path tool settings when already present.
            if hasattr(existing_tools, tool_name):
                continue
            OmegaConf.update(config, f'tools.{tool_name}', tool_cfg, merge=True)

    return config


@contextlib.contextmanager
def _redirect_stdout():
    """Redirect stdout to stderr while running an in-process LLMAgent.

    MCP stdio transport uses stdout for JSONRPC messages.  LLMAgent.step()
    writes streaming content and reasoning to sys.stdout, which would
    corrupt the protocol.  Redirecting to stderr keeps the channel clean
    while still allowing the output to appear in server logs.
    """
    old_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield
    finally:
        sys.stdout = old_stdout


async def _run_agent(
    query: str,
    system_prompt: str | None = None,
    tools_list: list[str] | None = None,
    max_rounds: int = 20,
    config_path: str | None = None,
) -> str:
    """Create, run, and clean up an LLMAgent.  Returns the response text."""
    from ms_agent.agent.llm_agent import LLMAgent

    config = _build_agent_config(config_path, system_prompt, tools_list, max_rounds)
    agent = LLMAgent(config=config, tag='delegate')

    try:
        with _redirect_stdout():
            result = await agent.run(query)

        # result is List[Message] -- extract assistant replies
        if isinstance(result, list):
            parts = []
            for m in result:
                if m.role == 'assistant' and m.content:
                    parts.append(m.content)
            return '\n'.join(parts) if parts else ''
        return str(result)
    finally:
        try:
            if agent.tool_manager:
                with _redirect_stdout():
                    await agent.cleanup_tools()
        except Exception:
            logger.debug('Error during agent tool cleanup', exc_info=True)


async def _handle_delegate_task(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Synchronous agent delegation -- blocks until the agent finishes."""
    query = (args.get('query') or '').strip()
    if not query:
        return {'error': 'query is required'}

    try:
        response = await _run_agent(
            query=query,
            system_prompt=args.get('system_prompt'),
            tools_list=_parse_tools_str(args.get('tools')),
            max_rounds=args.get('max_rounds', 20),
            config_path=args.get('config_path'),
        )
        return {'status': 'completed', 'response': response}
    except Exception as exc:
        return {'status': 'failed', 'error': str(exc)}


async def _background_agent(task: AsyncTask) -> dict[str, Any]:
    """Background coroutine for async agent delegation."""
    meta = task.metadata
    response = await _run_agent(
        query=meta['query'],
        system_prompt=meta.get('system_prompt'),
        tools_list=meta.get('tools_list'),
        max_rounds=meta.get('max_rounds', 20),
        config_path=meta.get('config_path'),
    )
    return {'response': response}


async def _handle_submit_agent_task(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Submit an agent task to run in the background."""
    query = (args.get('query') or '').strip()
    if not query:
        return {'error': 'query is required'}

    task = _manager.submit(
        task_type='agent_delegate',
        coroutine_fn=_background_agent,
        metadata={
            'query': query,
            'system_prompt': args.get('system_prompt'),
            'tools_list': _parse_tools_str(args.get('tools')),
            'max_rounds': args.get('max_rounds', 20),
            'config_path': args.get('config_path'),
        },
    )
    return {
        'task_id': task.task_id,
        'status': 'running',
        'message': (
            f'Agent task {task.task_id} started. Use check_agent_task(task_id="{task.task_id}") to poll status.'
        ),
    }


async def _handle_check_agent_task(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Check progress of a background agent task."""
    return _manager.check(args['task_id'])


async def _handle_get_agent_result(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Get the result of a completed agent task."""
    task_id = args['task_id']
    max_chars = args.get('max_chars', 50000)
    result = _manager.get_result(task_id)

    # Truncate response if needed
    if result.get('status') == 'completed' and isinstance(result.get('result'), dict):
        response = result['result'].get('response', '')
        truncated = len(response) > max_chars
        if truncated:
            response = response[:max_chars] + '\n\n... [truncated]'
        result['response'] = response
        result['truncated'] = truncated
        del result['result']  # replace raw result with formatted response

    return result


async def _handle_cancel_agent_task(args: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Cancel a running agent task."""
    return await _manager.cancel(args['task_id'])


def register_all(registry: CapabilityRegistry, config: Any = None) -> None:
    """Register agent delegate capabilities into the registry."""
    # Sync
    registry.register(DELEGATE_TASK_DESCRIPTOR, _handle_delegate_task)
    # Async quartet
    registry.register(SUBMIT_AGENT_TASK_DESCRIPTOR, _handle_submit_agent_task)
    registry.register(CHECK_AGENT_TASK_DESCRIPTOR, _handle_check_agent_task)
    registry.register(GET_AGENT_RESULT_DESCRIPTOR, _handle_get_agent_result)
    registry.register(CANCEL_AGENT_TASK_DESCRIPTOR, _handle_cancel_agent_task)
