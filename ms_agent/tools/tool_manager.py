# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import importlib
import inspect
import json
import math
import os
import sys
import uuid
from copy import copy
from types import TracebackType
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool, ToolCall
from ms_agent.tools.agent_tool import AgentTool
from ms_agent.tools.base import ToolBase
from ms_agent.tools.code import CodeExecutionTool, LocalCodeExecutionTool
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.tools.image_generator import ImageGenerator
try:
    from ms_agent.tools.mcp_client import MCPClient
except ImportError:
    MCPClient = None
from ms_agent.tools.search.localsearch_tool import LocalSearchTool
from ms_agent.tools.search.sirchmunk_search import \
    effective_localsearch_settings
from ms_agent.tools.search.websearch_tool import WebSearchTool
from ms_agent.tools.todolist_tool import TodoListTool
from ms_agent.tools.video_generator import VideoGenerator
from ms_agent.utils import get_logger
from ms_agent.utils.constants import TOOL_PLUGIN_NAME

logger = get_logger()

MAX_TOOL_NAME_LEN = int(os.getenv('MAX_TOOL_NAME_LEN', 64))
# Default wait around each tool invocation (seconds). Override via config.tool_call_timeout or TOOL_CALL_TIMEOUT.
TOOL_CALL_TIMEOUT = int(os.getenv('TOOL_CALL_TIMEOUT', 120))
# Hard ceiling for a single tool call, including model-provided ``timeout`` in tool arguments.
TOOL_CALL_TIMEOUT_MAX = int(os.getenv('TOOL_CALL_TIMEOUT_MAX', 600))
MAX_CONCURRENT_TOOLS = int(os.getenv('MAX_CONCURRENT_TOOLS', 20))


def parse_timeout_from_tool_args(
        tool_args: Optional[Dict[str, Any]]) -> Optional[float]:
    """Read ``tools.arguments.timeout`` if present (even when omitted from JSON schema).

    Providers may still drop unknown keys before arguments reach the host; when the key
    is present, it is honored here for the asyncio wait around ``call_tool``.
    """
    if not isinstance(tool_args, dict) or 'timeout' not in tool_args:
        return None
    raw = tool_args['timeout']
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        logger.warning('Ignoring invalid tools.arguments.timeout: %r', raw)
        return None
    if v != v:  # NaN
        return None
    return v


def effective_tool_wait_seconds(
        tool_args: Optional[Dict[str, Any]],
        *,
        default_sec: float,
        max_sec: float,
) -> float:
    """Per-call wait: ``min(max(requested, 1), max_sec)`` if ``timeout`` set, else clamped default."""
    cap = max(1.0, float(max_sec))
    base = min(max(float(default_sec), 1.0), cap)
    req = parse_timeout_from_tool_args(tool_args)
    if req is None:
        return base
    return min(max(req, 1.0), cap)


class ToolManager:
    """Interacting with Agent class, hold all tools
    """

    TOOL_SPLITER = '---'

    @staticmethod
    def _registered_tool_suffix(full_name: str, splitter: str) -> str:
        """Return segment after first *splitter* (tool ids may themselves contain *splitter*)."""
        if splitter not in full_name:
            return full_name
        return full_name.split(splitter, 1)[1]

    def __init__(self,
                 config,
                 mcp_config: Optional[Dict[str, Any]] = None,
                 mcp_client: Optional[MCPClient] = None,
                 **kwargs):
        self.config = config
        self.trust_remote_code = kwargs.get('trust_remote_code', False)

        self.extra_tools: List[ToolBase] = []
        self.has_split_task_tool = False
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'image_generator'):
            self.extra_tools.append(ImageGenerator(config))
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'video_generator'):
            self.extra_tools.append(VideoGenerator(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'file_system'):
            self.extra_tools.append(
                FileSystemTool(
                    config, trust_remote_code=self.trust_remote_code))
        if hasattr(config, 'tools') and hasattr(config.tools, 'code_executor'):
            code_exec_cfg = getattr(config.tools, 'code_executor')
            implementation = getattr(code_exec_cfg, 'implementation',
                                     'sandbox')
            if isinstance(implementation,
                          str) and implementation.lower() == 'python_env':
                self.extra_tools.append(LocalCodeExecutionTool(config))
            elif isinstance(implementation,
                            str) and implementation.lower() == 'sandbox':
                self.extra_tools.append(CodeExecutionTool(config))
            else:
                logger.warning(
                    f'Unknown code execution implementation: {implementation},'
                    f'using sandbox instead.')
                self.extra_tools.append(CodeExecutionTool(config))
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                'financial_data_fetcher'):
            from ms_agent.tools.findata.findata_fetcher import \
                FinancialDataFetcher
            self.extra_tools.append(FinancialDataFetcher(config))
        if hasattr(config,
                   'tools') and (getattr(config.tools, 'agent_tools', None)
                                 or hasattr(config.tools, 'split_task')):
            agent_tool = AgentTool(
                config, trust_remote_code=self.trust_remote_code)
            if agent_tool.enabled:
                self.extra_tools.append(agent_tool)
        if hasattr(config, 'tools') and hasattr(config.tools, 'todo_list'):
            self.extra_tools.append(TodoListTool(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'web_search'):
            self.extra_tools.append(WebSearchTool(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'cron'):
            cron_cfg = getattr(config.tools, 'cron', None)
            if not getattr(cron_cfg, 'mcp', False):
                from ms_agent.tools.cron_tool import CronTool
                self.extra_tools.append(CronTool(config))
        if effective_localsearch_settings(config) is not None:
            self.extra_tools.append(LocalSearchTool(config))
        if hasattr(config, 'tools') and hasattr(config.tools, 'task_control'):
            from ms_agent.tools.task_control_tool import TaskControlTool
            self.extra_tools.append(TaskControlTool(config))
        try:
            from ms_agent.tools.acp_agent_tool import ACPAgentTool
            acp_tool = ACPAgentTool.from_config(config)
            if acp_tool is not None:
                self.extra_tools.append(acp_tool)
        except ImportError:
            pass
        try:
            from ms_agent.tools.a2a_agent_tool import A2AAgentTool
            a2a_tool = A2AAgentTool.from_config(config)
            if a2a_tool is not None:
                self.extra_tools.append(a2a_tool)
        except ImportError:
            pass
        self.tool_call_timeout = float(
            getattr(config, 'tool_call_timeout', TOOL_CALL_TIMEOUT))
        self.tool_call_timeout_max = float(
            getattr(config, 'tool_call_timeout_max', TOOL_CALL_TIMEOUT_MAX))
        local_dir = self.config.local_dir if hasattr(self.config,
                                                     'local_dir') else None
        if hasattr(config, 'tools') and hasattr(config.tools,
                                                TOOL_PLUGIN_NAME):
            plugins = getattr(config.tools, TOOL_PLUGIN_NAME)
            for plugin in plugins:
                subdir = os.path.dirname(plugin)
                _plugin = os.path.basename(plugin)
                assert local_dir is not None, 'Using external py files, but local_dir cannot be found.'
                if subdir:
                    subdir = os.path.join(local_dir, str(subdir))
                if not self.trust_remote_code:
                    raise AssertionError(
                        '[External Code Found] Your config file contains external code, '
                        'instantiate the code may be UNSAFE, if you trust the code, '
                        'please pass `trust_remote_code=True` or `--trust_remote_code true`'
                    )
                if local_dir not in sys.path:
                    sys.path.insert(0, local_dir)
                if subdir and subdir not in sys.path:
                    sys.path.insert(0, subdir)
                if _plugin.endswith('.py'):
                    _plugin = _plugin[:-3]
                plugin_file = importlib.import_module(_plugin)
                module_classes = {
                    name: cls
                    for name, cls in inspect.getmembers(
                        plugin_file, inspect.isclass)
                }
                for name, cls in module_classes.items():
                    # Find cls which base class is `ToolBase`
                    if issubclass(cls, ToolBase) and cls.__module__ == _plugin:
                        self.register_tool(cls(self.config))
        self._tool_index = {}

        # Used temporarily during async initialization; the actual client is managed in self.servers
        self.mcp_client = mcp_client
        self.mcp_config = mcp_config
        self.servers = None
        self._managed_client = mcp_client is None

        # Initialize concurrency limiter (will be set in connect)
        self._concurrent_limiter = None
        self._init_lock = None

    def register_tool(self, tool: ToolBase):
        self.extra_tools.append(tool)

    async def connect(self):
        if self.mcp_client and MCPClient and isinstance(self.mcp_client, MCPClient):
            self.servers = self.mcp_client
            await self.servers.add_mcp_config(self.mcp_config)
            self.mcp_config = self.servers.mcp_config
        elif MCPClient is not None:
            self.servers = MCPClient(self.mcp_config, self.config)
            await self.servers.connect()
        for tool in self.extra_tools:
            await tool.connect()
        await self.reindex_tool()

        # Initialize concurrency limiter
        self._concurrent_limiter = asyncio.Semaphore(MAX_CONCURRENT_TOOLS)
        logger.info(f'Tool concurrency limit set to {MAX_CONCURRENT_TOOLS}')

    async def cleanup(self):
        if self._managed_client and self.servers:
            try:
                await self.servers.cleanup()
            except Exception:  # noqa
                pass
        self.servers = None
        for tool in self.extra_tools:
            try:
                await tool.cleanup()
            except Exception:  # noqa
                pass

    async def reindex_tool(self):

        def extend_tool(tool_ins: ToolBase, server_name: str,
                        tool_list: List[Tool]):
            for tool in tool_list:
                # Subtract the length of the tool name splitter
                max_server_len = MAX_TOOL_NAME_LEN - len(
                    tool['tool_name']) - len(self.TOOL_SPLITER)
                if len(server_name) > max_server_len:
                    key = f"{server_name[:max(0, max_server_len)]}{self.TOOL_SPLITER}{tool['tool_name']}"
                else:
                    key = f"{server_name}{self.TOOL_SPLITER}{tool['tool_name']}"
                if key in self._tool_index:
                    continue
                tool = copy(tool)
                tool['tool_name'] = key
                self._tool_index[key] = (tool_ins, server_name, tool)

        if self.servers is not None:
            mcps = await self.servers.get_tools()
            for server_name, tool_list in mcps.items():
                extend_tool(self.servers, server_name, tool_list)
        for extra_tool in self.extra_tools:
            tools = await extra_tool.get_tools()
            for server_name, tool_list in tools.items():
                extend_tool(extra_tool, server_name, tool_list)

    async def get_tools(self):
        # Return tools in deterministic order to improve prompt/prefix cache hit rate
        # across process restarts and across different MCP tool listing orders.
        tools = [value[2] for value in self._tool_index.values()]
        return sorted(tools, key=lambda t: (t.get('tool_name', ''), ))

    async def single_call_tool(self, tool_info: ToolCall):
        if self._concurrent_limiter is None:
            if self._init_lock is None:
                self._init_lock = asyncio.Lock()
            async with self._init_lock:
                if self._concurrent_limiter is None:
                    self._concurrent_limiter = asyncio.Semaphore(
                        MAX_CONCURRENT_TOOLS)

        async with self._concurrent_limiter:
            brief_info = json.dumps(tool_info, ensure_ascii=False)
            if len(brief_info) > 1024:
                brief_info = brief_info[:1024] + '...'
            try:
                tool_name = tool_info['tool_name']
                tool_args = tool_info['arguments']
                while isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:  # noqa
                        return f'The input {tool_args} is not a valid JSON, fix your arguments and try again'
                assert tool_name in self._tool_index, f'Tool name {tool_name} not found'
                tool_ins, server_name, _ = self._tool_index[tool_name]
                raw_args = dict(tool_args) if isinstance(tool_args, dict) else {}
                wait_sec = effective_tool_wait_seconds(
                    raw_args,
                    default_sec=self.tool_call_timeout,
                    max_sec=self.tool_call_timeout_max,
                )
                call_args = tool_args
                if isinstance(tool_ins, AgentTool):
                    call_args = dict(tool_args or {})
                    call_id = tool_info.get('id') or str(uuid.uuid4())
                    call_args['__call_id'] = call_id
                elif isinstance(tool_ins,
                                LocalCodeExecutionTool) and tool_name.endswith(
                                    f'{self.TOOL_SPLITER}shell_executor'):
                    call_args = dict(tool_args or {})
                    call_args['__call_id'] = tool_info.get('id') or str(
                        uuid.uuid4())
                    # Align subprocess wait with the host wait (after cap) so inner
                    # ``communicate`` does not expire before the outer ``wait_for``.
                    call_args['timeout'] = int(math.ceil(wait_sec))
                response = await asyncio.wait_for(
                    tool_ins.call_tool(
                        server_name,
                        tool_name=self._registered_tool_suffix(
                            tool_name, self.TOOL_SPLITER),
                        tool_args=call_args),
                    timeout=wait_sec)
                return response
            except asyncio.TimeoutError:
                import traceback
                logger.warning(traceback.format_exc())
                tn = tool_info.get('tool_name', '(unknown)')
                return (
                    f'Tool call timed out after {wait_sec:.0f}s (tool: {tn}). '
                    f'Default limit is {self.tool_call_timeout:.0f}s; '
                    f'set numeric field "timeout" in the tool arguments to wait longer '
                    f'(seconds, maximum {self.tool_call_timeout_max:.0f}s). '
                    f'Original call (truncated): {brief_info}')
            except Exception as e:
                import traceback
                logger.warning(traceback.format_exc())
                return f'Tool calling failed: {brief_info}, details: {str(e)}'

    async def parallel_call_tool(self, tool_list: List[ToolCall]):
        tasks = [self.single_call_tool(tool) for tool in tool_list]
        result = await asyncio.gather(*tasks)
        return result

    async def __aenter__(self) -> 'ToolManager':

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass
