from __future__ import annotations

# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import base64
import contextvars
import copy
import inspect
import json
import logging
import math
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
from contextlib import AsyncExitStack, suppress
from contextvars import ContextVar
from datetime import timedelta
from mcp import ClientSession, ListToolsResult, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from omegaconf import DictConfig
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional

from ms_agent.config import Config
from ms_agent.config.env import Env
from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger
from ms_agent.utils.package_env import PACKAGE_ENV_PASSTHROUGH

logger = get_logger()


def _session_read_timeout(seconds: float):
    """Value ``ClientSession`` accepts for ``read_timeout_seconds``.

    mcp 1.x takes a ``timedelta``. mcp 2.x takes seconds as a float and
    adds that number to ``anyio.current_time()``.
    """
    param = inspect.signature(
        ClientSession.__init__).parameters.get('read_timeout_seconds')
    annotation = '' if param is None else str(param.annotation)
    if 'timedelta' in annotation and 'float' not in annotation:
        return timedelta(seconds=seconds)
    return float(seconds)


def _tool_call_is_error(response) -> bool:
    """Whether an MCP ``call_tool`` result is an error.

    mcp 1.x exposes ``isError``. mcp 2.x renamed it to ``is_error``.
    """
    flag = getattr(response, 'is_error', None)
    if flag is None:
        flag = getattr(response, 'isError', None)
    return bool(flag)


def _tool_output_schema(tool):
    """Return schema, whichever spelling this SDK version uses."""
    schema = getattr(tool, 'output_schema', None)
    if schema is None:
        schema = getattr(tool, 'outputSchema', None)
    return schema if isinstance(schema, dict) else None


def _describe_tool(tool) -> str:
    """Description plus the declared return shape.

    The chat-completions tool object only has a description, so a server that
    published an output schema would otherwise never show the model what a
    successful call looks like.
    """
    description = getattr(tool, 'description', None) or ''
    schema = _tool_output_schema(tool)
    if not schema:
        return description
    rendered = json.dumps(schema, ensure_ascii=False)
    if len(rendered) > 800:
        rendered = rendered[:800] + '…'
    return f'{description}\nReturns: {rendered}'.strip()


def _structured_content(response):
    value = getattr(response, 'structured_content', None)
    if value is None:
        value = getattr(response, 'structuredContent', None)
    return value


def _content_mime(content) -> str:
    mime = getattr(content, 'mime_type', None)
    if not mime:
        mime = getattr(content, 'mimeType', None)
    return str(mime or 'application/octet-stream')


def _resource_json(resource) -> str:
    """Serialize an embedded resource on either SDK spelling."""
    dump_json = getattr(resource, 'model_dump_json', None)
    if callable(dump_json):
        try:
            return dump_json(by_alias=True)
        except TypeError:
            return dump_json()
    dump = getattr(resource, 'model_dump', None)
    if callable(dump):
        try:
            return json.dumps(dump(by_alias=True), ensure_ascii=False)
        except TypeError:
            return json.dumps(dump(), ensure_ascii=False)
    if isinstance(resource, dict):
        return json.dumps(resource, ensure_ascii=False)
    return json.dumps(getattr(resource, '__dict__', str(resource)),
                      default=str,
                      ensure_ascii=False)


def _tool_input_schema(tool) -> dict:
    """JSON schema for one MCP tool.

    mcp 1.x exposes ``inputSchema``. mcp 2.x renamed it to ``input_schema``
    and dropped the old attribute.
    """
    schema = getattr(tool, 'input_schema', None)
    if schema is None:
        schema = getattr(tool, 'inputSchema', None)
    if isinstance(schema, dict):
        return schema
    return {'type': 'object', 'properties': {}}


def _retrieve_future(fut) -> None:
    """Mark a finished future's exception as retrieved.

    ``ready.set_exception(CancelledError())`` inside a connect that quit
    cancelled otherwise logs ``Future exception was never retrieved`` when the
    loop later garbage-collects it — after the user has already seen bye.
    """
    if fut is None or not fut.done() or fut.cancelled():
        return
    try:
        fut.exception()
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        return


def _is_teardown_noise(exc: BaseException) -> bool:
    """MCP SDK / anyio errors that fire when closing streamable_http."""
    text = f'{type(exc).__name__}: {exc}'
    return any(s in text for s in (
        'cancel scope',
        'athrow()',
        'asynchronous generator',
    ))


EncodingErrorHandler = Literal['strict', 'ignore', 'replace']

DEFAULT_ENCODING = 'utf-8'
DEFAULT_ENCODING_ERROR_HANDLER: EncodingErrorHandler = 'strict'

DEFAULT_HTTP_TIMEOUT = 5
DEFAULT_SSE_READ_TIMEOUT = 60 * 5


def _int_env(name: str, default: int) -> int:
    """``os.getenv`` hands back a STRING once the variable is set, and these
    values end up in ``timedelta(seconds=...)``, which rejects one."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


CONNECTION_TIMEOUT = _int_env('CONNECTION_TIMEOUT', 120)

#: Cap for one remote MCP handshake. WebUI's health check uses the same 6
#: seconds. A dead address must not sit on ``CONNECTION_TIMEOUT`` (120s).
#: stdio does not use this as a death sentence: a local command keeps
#: ``DEFAULT_SERVER_STARTUP_TIMEOUT`` in the background, and a turn only
#: waits ``MCP_TURN_WAIT``.
MCP_PROBE_TIMEOUT = 6

#: How many servers may be started at once. Bounded because each stdio server
#: is a child process and a large config would otherwise fork all of them
#: simultaneously.
MAX_PARALLEL_CONNECTS = _int_env('MCP_MAX_PARALLEL_CONNECTS', 8)

#: How long to wait for a server's owner task to close its transport before
#: cancelling it outright.
SERVER_STOP_TIMEOUT = _int_env('MCP_STOP_TIMEOUT', 15)

#: Per-server startup ceiling (spawn/dial + initialize + first list_tools).
#: Without it a stdio server that never answers — a cold ``uvx`` still
#: resolving, a wrapper whose upstream 403s — parks the whole connect,
#: and with servers brought up together that is a session that never
#: finishes preparing its tools.
DEFAULT_SERVER_STARTUP_TIMEOUT = _int_env('MCP_STARTUP_TIMEOUT', 60)

DEFAULT_STREAMABLE_HTTP_TIMEOUT = timedelta(seconds=30)
DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT = timedelta(seconds=60 * 5)

#: Variables a stdio server's child process inherits from this one. The MCP
#: SDK's default child environment is deliberately tiny, which strips proxy,
#: TLS and package-index settings — a cold ``uvx <package>`` then downloads
#: without the proxy the machine needs and runs into the startup timeout.
#: Identity, toolchain and network settings pass through; credentials do not.
#: A server's configured ``env`` is applied on top and wins per key.
_STDIO_ENV_PASSTHROUGH = (
    'PATH',
    'HOME',
    'USER',
    'LOGNAME',
    'SHELL',
    'TMPDIR',
    'TERM',
    'TZ',
    'LANG',
    'LC_ALL',
    'LC_CTYPE',
    'SSL_CERT_FILE',
    'SSL_CERT_DIR',
    'REQUESTS_CA_BUNDLE',
    # ALL_PROXY is deliberately absent: a socks5:// value makes any child
    # whose httpx lacks the socksio extra fail on its FIRST request, and the
    # child's venv is not ours to fix. The scheme-specific variables cover
    # the download-acceleration need without that trap.
    'HTTP_PROXY',
    'HTTPS_PROXY',
    'NO_PROXY',
    'http_proxy',
    'https_proxy',
    'no_proxy',
    'CURL_CA_BUNDLE',
    'NODE_EXTRA_CA_CERTS',
) + PACKAGE_ENV_PASSTHROUGH

#: Where a bare stdio command is looked for when PATH does not know it. A
#: backend launched by an IDE or launchd runs with a minimal PATH while the
#: user's ``uvx``/``npx`` lives in one of these.
_STDIO_EXTRA_BIN_DIRS = (
    os.path.expanduser('~/.local/bin'),
    '/opt/homebrew/bin',
    '/usr/local/bin',
)


def stdio_child_env(config_env: Optional[dict]) -> dict:
    env = {
        key: os.environ[key]
        for key in _STDIO_ENV_PASSTHROUGH if os.environ.get(key)
    }
    for key, value in (config_env or {}).items():
        env[str(key)] = str(value)
    return env


# The stdio helper keeps the child private. This records it for the task
# that is opening the server, so a later turn can read ``returncode``.
_stdio_child: 'contextvars.ContextVar[list[Any] | None]' = (
    contextvars.ContextVar('ms_agent_stdio_child', default=None))


def _install_stdio_child_hook() -> None:
    """Remember the process ``stdio_client`` just spawned.

    The MCP helper does not return that process. Missing the private
    function is safe: death is then noticed when the session itself drops.
    """
    try:
        import mcp.client.stdio as stdio_mod
    except ImportError:
        return
    current = getattr(stdio_mod, '_create_platform_compatible_process', None)
    if current is None or getattr(current, '_ms_agent_stdio_hook', False):
        return

    async def hooked(*args, **kwargs):
        process = await current(*args, **kwargs)
        holder = _stdio_child.get()
        if holder is not None:
            holder.append(process)
        return process

    hooked._ms_agent_stdio_hook = True  # type: ignore[attr-defined]
    stdio_mod._create_platform_compatible_process = hooked


def resolve_stdio_command(command: str) -> str:
    """Absolute path for *command*, searching PATH then the usual user dirs."""
    if os.path.sep in command:
        return command
    found = shutil.which(command)
    if found:
        return found
    for base in _STDIO_EXTRA_BIN_DIRS:
        candidate = os.path.join(base, command)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    searched = ':'.join([os.environ.get('PATH', '')]
                        + list(_STDIO_EXTRA_BIN_DIRS))
    raise FileNotFoundError(
        f"stdio MCP command '{command}' was not found on this machine. "
        f'Searched: {searched}')


_PYDANTIC_DOC_LINK = re.compile(r'\s*For further information visit \S+')
_PYDANTIC_FIELD_LINE = re.compile(r'^(\S+?)(?:\.\w+)?\n\s+(.+?)\s*\[type=',
                                  re.MULTILINE)


def _summarize_tool_error(detail: str) -> str:
    """Make a validator's complaint answerable.

    A union of strict types reports once per branch, so rejecting two quoted
    numbers arrives as four near-identical paragraphs, each ending in a link to
    the validation library's documentation. None of that tells the model what
    to send instead, and its length buries the one line that does. The
    per-field expectation is lifted to the front; the original follows for
    anyone reading the transcript.
    """
    if 'validation error' not in detail:
        return detail

    seen: dict = {}
    for field, message in _PYDANTIC_FIELD_LINE.findall(detail):
        seen.setdefault(field, message)
    if not seen:
        return _PYDANTIC_DOC_LINK.sub('', detail).strip()

    lines = [f'- `{field}`: {message}' for field, message in seen.items()]
    return ('the arguments were rejected by the tool:\n' + '\n'.join(lines)
            + '\nSend each value as its declared JSON type (a number '
            'unquoted, not as a string) and call again.\n\nOriginal error:\n'
            + _PYDANTIC_DOC_LINK.sub('', detail).strip())


class _MCPStartupError(RuntimeError):
    """A startup diagnostic composed exclusively from controlled summaries."""


_MCP_TRANSPORT_CONTEXT = ContextVar('mcp_transport_diagnostics', default=False)


class _MCPTransportLogFilter(logging.Filter):

    def filter(self, record):
        if _MCP_TRANSPORT_CONTEXT.get():
            # Dependencies log URLs, protocol bodies and validation tracebacks.
            # Sanitize the record before any handler (including file handlers)
            # sees it. Other tasks using the same libraries are unaffected.
            record.msg = 'MCP transport diagnostic (external details withheld).'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


_MCP_TRANSPORT_LOG_FILTER = _MCPTransportLogFilter()


def _protect_transport_logs():
    # Seed lazy transport loggers as well as already-loaded dependency loggers.
    names = {
        'mcp.client.stdio',
        'mcp.client.sse',
        'mcp.client.streamable_http',
        'mcp.client.websocket',
        'mcp.shared.session',
        'httpx',
        'httpcore.connection',
        'httpcore.http11',
        'httpcore.http2',
        'httpcore.proxy',
        'httpcore.socks',
        'websockets.client',
    }
    names.update(
        name for name in list(logging.Logger.manager.loggerDict)
        if name.startswith(('mcp.', 'httpcore.', 'websockets.')))
    for name in names:
        logging.getLogger(name).addFilter(_MCP_TRANSPORT_LOG_FILTER)


def safe_mcp_error(exc: BaseException, server: dict | None = None) -> str:
    """Summarize untrusted diagnostics without copying their text.

    Redaction cannot recognize every credential (argv, DSNs, escaped values,
    or secrets loaded by the peer itself). Only fixed descriptions and HTTP
    status codes may cross the diagnostic boundary. ``server`` is retained
    for callers using the previous signature; its values are never emitted.
    """
    while isinstance(getattr(exc, 'exceptions', None),
                     tuple) and exc.exceptions:
        exc = exc.exceptions[0]
    if type(exc) is _MCPStartupError:
        return str(exc)
    text = str(exc).lower()
    status = re.search(
        r'\b(?:http(?:/\d(?:\.\d)?)?\s+|status(?:\s+code)?[=:]?\s*'
        r'|(?:client|server) error\s+[\'"]?)([45]\d{2})\b', text)
    if status:
        code = status[1]
        if code in ('401', '403'):
            return f'HTTP {code}: access denied; check MCP credentials and permissions.'
        return f'HTTP {code}: the remote service or package source rejected the request.'
    if isinstance(exc, TimeoutError) or re.search(r'timed out|timeout', text):
        return 'MCP startup timed out.'
    if isinstance(exc, FileNotFoundError):
        return 'MCP command or required file not found.'
    if isinstance(exc, PermissionError) or 'permission denied' in text:
        return 'Permission denied while starting MCP.'
    if isinstance(exc, ImportError) or re.search(
            r'no module named|cannot import', text):
        return 'An MCP dependency is missing or incompatible.'
    if re.search(
            r'connection closed|session closed|session terminated|broken pipe',
            text):
        return 'MCP connection closed before startup completed.'
    if isinstance(exc, ConnectionError) or 'connection refused' in text:
        return 'Could not connect to the MCP service.'
    if isinstance(exc, (ValueError, TypeError, AttributeError)):
        return 'Invalid MCP configuration or protocol response.'
    return 'MCP startup failed; external diagnostic details were withheld.'


class MCPClient(ToolBase):
    """MCP client for all mcp tools

    This class can hold multiple mcp servers.

    Args:
        config(`DictConfig`): The config instance.
        mcp_config(`Optional[Dict[str, Any]]`): Extra mcp servers in json format.
    """

    def __init__(
        self,
        mcp_config: Optional[Dict[str, Any]] = None,
        config: Optional[DictConfig] = None,
    ):
        super().__init__(config)
        self.sessions: Dict[str, ClientSession] = {}
        self.startup_failures: Dict[str, str] = {}
        self.startup_phases: Dict[str, str] = {}
        self._initial_tools: Dict[str, ListToolsResult] = {}
        # One owner task per server, holding that server's transport open for
        # its whole lifetime (see _own_server), plus the event that asks it to
        # let go.
        self._server_tasks: Dict[str, 'asyncio.Task'] = {}
        self._server_shutdown: Dict[str, asyncio.Event] = {}
        # The Future ``connect_to_server`` waits on. Kept so a cancelled
        # connect can still retrieve the CancelledError it stored there.
        self._server_ready: Dict[str, 'asyncio.Future'] = {}
        # Every owner task, including ones already popped from ``_server_tasks``
        # while their teardown is still running.
        self._live_tasks: set['asyncio.Task'] = set()
        # stdio children, so a later turn can see that the process exited
        # while this session object is still registered.
        self._stdio_children: Dict[str, Any] = {}
        self.exit_stack = AsyncExitStack()
        self.mcp_config: Dict[str, Dict[str, Any]] = {'mcpServers': {}}
        if config is not None:
            config_from_file = Config.convert_mcp_servers_to_json(config)
            self.mcp_config['mcpServers'].update(
                config_from_file.get('mcpServers', {}))
        self.exclude_functions = {}
        self.include_functions = {}
        if mcp_config is not None:
            self.mcp_config['mcpServers'].update(
                mcp_config.get('mcpServers', {}))

    async def call_tool(self, server_name: str, tool_name: str,
                        tool_args: dict):
        session = self.sessions.get(server_name)
        if session is None:
            # The server's tools stay in the tool index after its connection
            # dies (a failed call tears the session down), so the model can
            # still address it — and used to get a bare KeyError. Name what
            # actually happened and what to do instead.
            raise RuntimeError(
                f"MCP server '{server_name}' is not connected (it failed or "
                'was disconnected earlier in this conversation). Its tools '
                'are unavailable for now — do not retry this call; use a '
                'different approach or tell the user the server is down.')
        response = await session.call_tool(tool_name, tool_args)

        texts = []
        resources = []
        attachments = []
        if _tool_call_is_error(response):
            sep = '\n\n'
            if all(isinstance(item, str) for item in response.content):
                detail = sep.join(response.content)
            else:
                detail = sep.join(
                    getattr(item, 'text', str(item))
                    for item in response.content)
            # Marked as an error rather than returned as ordinary text. A
            # failure reported only in prose reaches the model with no error
            # flag and reaches the UI with no failed step, so a call that was
            # refused looks like a call that answered.
            return {
                'result':
                (f'execute tool call error: [{server_name}]{tool_name}, '
                 f'{_summarize_tool_error(detail)}'),
                'is_error':
                True,
            }
        for content in response.content or []:
            kind = getattr(content, 'type', None)
            if kind == 'text':
                texts.append(content.text)
            elif kind == 'resource':
                import json5
                json_str = _resource_json(content.resource)
                texts.append(json_str)
                resources.append(json5.loads(json_str))
            elif kind == 'image':
                path = self._write_media(
                    getattr(content, 'data', '') or '',
                    _content_mime(content), 'image')
                attachments.append({
                    'type': 'image',
                    'path': path,
                    'media_type': _content_mime(content),
                    'label': f'Image: {os.path.basename(path)}',
                })
                texts.append(f'Image returned ({_content_mime(content)}).')
            elif kind == 'audio':
                path = self._write_media(
                    getattr(content, 'data', '') or '',
                    _content_mime(content), 'audio')
                texts.append(
                    f'Audio returned ({_content_mime(content)}), saved at {path}.')

        structured = _structured_content(response)
        if structured is not None and not texts:
            texts.append(
                json.dumps(structured, ensure_ascii=False, default=str))

        body = '\n\n'.join(texts)
        if resources or attachments:
            result = {'text': body}
            if resources:
                result['resources'] = resources
            if attachments:
                result['attachments'] = attachments
            return result
        return body

    def _write_media(self, data: str, mime: str, kind: str) -> str:
        """Persist a base64 tool result next to the workspace.

        Image refs the model can see are file paths, not inline bytes. Audio
        has no model channel, so the path in the text is the whole delivery.
        """
        raw = base64.b64decode(data or '')
        ext = mimetypes.guess_extension(mime.split(';', 1)[0].strip()) or ''
        if ext == '.jpe':
            ext = '.jpg'
        if not ext:
            ext = '.png' if kind == 'image' else '.bin'
        root = self.output_dir or os.getcwd()
        folder = os.path.join(root, 'mcp_media')
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f'{uuid.uuid4().hex}{ext}')
        with open(path, 'wb') as handle:
            handle.write(raw)
        return os.path.relpath(path, root)

    def _filter_session_tools(
        self,
        server_name: str,
        response: ListToolsResult,
    ) -> List[Tool]:
        exclude: list[str] = []
        include: list[str] = []
        if self.include_functions and server_name in self.include_functions:
            include = self.include_functions[server_name]
        elif self.exclude_functions and server_name in self.exclude_functions:
            exclude = self.exclude_functions[server_name]
        session_tools = [t for t in response.tools if t.name not in exclude]
        if include:
            session_tools = [t for t in session_tools if t.name in include]
        return [
            Tool(
                tool_name=t.name,
                server_name=server_name,
                description=_describe_tool(t),
                parameters=_tool_input_schema(t),
            ) for t in session_tools
        ]

    async def get_tools_for_server(self, server_name: str) -> List[Tool]:
        """List tools for a single connected server (failures are isolated)."""
        session = self.sessions.get(server_name)
        if session is None:
            return []
        try:
            response = self._initial_tools.pop(server_name, None)
            if response is None:
                response = await session.list_tools()
        except Exception as e:
            raise _MCPStartupError(safe_mcp_error(e)) from None
        # Logged from here rather than from connect(): the same listing that
        # registers the tools also reports them, so the log costs no extra
        # round trip to the server.
        self.print_tools(server_name, response)
        return self._filter_session_tools(server_name, response)

    async def get_tools(self) -> Dict:
        tools: Dict[str, List[Tool]] = {}
        for key in list(self.sessions):
            try:
                tools[key] = await self.get_tools_for_server(key)
            except Exception as e:
                logger.warning('Skipping MCP server %s in get_tools: %s', key,
                               e)
                tools[key] = []
        return tools

    @staticmethod
    def print_tools(server_name: str, tools: ListToolsResult):
        tools = tools.tools
        sep = ','
        if len(tools) > 10:
            tools = [tool.name for tool in tools][:10]
            logger.info(
                f'\nConnected to server "{server_name}" '
                f'with tools: \n{sep.join(tools)}\nOnly list first 10 of them.'
            )
        else:
            tools = [tool.name for tool in tools]
            logger.info(f'\nConnected to server "{server_name}" '
                        f'with tools: \n{sep.join(tools)}.')

    @staticmethod
    def resolve_server_env(server: Dict[str, Any]) -> Dict[str, str]:
        envs = Env.load_env()
        configured = server.get('env')
        env_dict = copy.deepcopy({} if configured is None else configured)
        if not isinstance(env_dict, dict):
            raise ValueError('MCP env must be a mapping')
        return {
            key: value if value else envs.get(key, '')
            for key, value in env_dict.items()
        }

    def list_connected_servers(self) -> list[str]:
        return list(self.sessions.keys())

    def is_connected(self, server_name: str) -> bool:
        return server_name in self.sessions

    def stdio_process_exited(self, server_name: str) -> bool:
        """Whether the stdio child has already exited.

        The session can still be registered: the owner task is blocked
        until something asks it to stop. ``returncode`` is the fact.
        """
        process = self._stdio_children.get(server_name)
        if process is None:
            return False
        return getattr(process, 'returncode', None) is not None

    def _track_task(self, task: 'asyncio.Task') -> None:
        self._live_tasks.add(task)
        task.add_done_callback(self._live_tasks.discard)
        task.add_done_callback(_retrieve_future)

    async def disconnect_server(self,
                                server_name: str,
                                *,
                                graceful: bool = True) -> None:
        """Disconnect a single MCP server."""
        self.exclude_functions.pop(server_name, None)
        self.include_functions.pop(server_name, None)
        await self._stop_server(server_name, graceful=graceful)

    async def connect_single_server(
        self,
        server_name: str,
        server_config: Dict[str, Any],
        timeout: int = CONNECTION_TIMEOUT,
        startup_timeout: Optional[float] = None,
    ) -> str:
        """Connect one server from a normalized config entry."""
        if self.is_connected(server_name):
            return server_name
        self.startup_failures.pop(server_name, None)
        try:
            plan = self._plan_server(server_name, server_config, timeout)
            plan.setdefault('startup_timeout', startup_timeout)
            return await self.connect_to_server(**plan)
        except Exception as exc:
            reason = self.startup_failures.setdefault(
                server_name, safe_mcp_error(exc, server_config))
            error_type = TimeoutError if isinstance(
                exc, TimeoutError) else _MCPStartupError
            raise error_type(reason) from None

    async def _open_session(self, stack: AsyncExitStack, server_name: str,
                            timeout: int, **kwargs) -> ClientSession:
        """Open the transport for one server and return its initialized session.

        Every context entered here is registered on ``stack``, which the
        caller must also close — see :meth:`_own_server` for why that has to
        happen in the same task.
        """
        # transport: stdio, sse, streamable_http, websocket
        transport = kwargs.get('transport') or kwargs.get('type')
        command = kwargs.get('command')
        url = kwargs.get('url')
        session_kwargs = copy.deepcopy(kwargs.get('session_kwargs'))
        self.startup_phases[server_name] = 'connect'
        if url:
            if transport and transport.lower() == 'sse':
                logger.info(
                    '`transport` or `type` is configured as "sse", using sse transport.'
                )
                sse_transport = await stack.enter_async_context(
                    sse_client(
                        url, kwargs.get('headers'),
                        kwargs.get('timeout', DEFAULT_HTTP_TIMEOUT),
                        kwargs.get('sse_read_timeout',
                                   DEFAULT_SSE_READ_TIMEOUT)))
                read, write = sse_transport

            elif transport and transport.lower() == 'websocket':
                logger.info(
                    '`transport` or `type` is configured as "websocket", using websocket transport.'
                )
                try:
                    from mcp.client.websocket import websocket_client
                except ImportError:
                    raise ImportError(
                        'Could not import websocket_client. '
                        'To use Websocket connections, please install the required dependency with: '
                        "'pip install mcp[ws]' or 'pip install websockets'"
                    ) from None
                websocket_transport = await stack.enter_async_context(
                    websocket_client(url))
                read, write = websocket_transport

            else:
                logger.info(
                    'Using streamable_http transport. To configure a different transport such as sse, please'
                    'set the `type` or `transport` variable to "sse".')
                try:
                    from mcp.client.streamable_http import \
                        streamablehttp_client
                except ImportError:
                    raise ImportError(
                        'Could not import streamablehttp_client. '
                        'To use streamable http connections, please upgrade to the latest version of mcp with: '
                        "'pip install -U mcp'") from None
                httpx_client_factory = kwargs.get('httpx_client_factory')
                other_kwargs = {}
                if httpx_client_factory is not None:
                    other_kwargs['httpx_client_factory'] = httpx_client_factory
                streamable_transport = await stack.enter_async_context(
                    streamablehttp_client(
                        url,
                        headers=kwargs.get('headers'),
                        timeout=kwargs.get('timeout',
                                           DEFAULT_STREAMABLE_HTTP_TIMEOUT),
                        sse_read_timeout=kwargs.get(
                            'sse_read_timeout',
                            DEFAULT_STREAMABLE_HTTP_SSE_READ_TIMEOUT),
                        **other_kwargs))
                read, write, _ = streamable_transport

            session_kwargs = session_kwargs or {}
            timeout = max(
                session_kwargs.pop('read_timeout_seconds', timeout), 1)
            session = await stack.enter_async_context(
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=_session_read_timeout(timeout),
                    **session_kwargs))

        elif command:
            # transport: 'stdio'
            args = kwargs.get('args') or []
            if os.name == 'nt':
                child_env = kwargs.get('env')
            else:
                command = resolve_stdio_command(command)
                child_env = stdio_child_env(kwargs.get('env'))
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=child_env,
                encoding=kwargs.get('encoding', DEFAULT_ENCODING),
                encoding_error_handler=kwargs.get(
                    'encoding_error_handler', DEFAULT_ENCODING_ERROR_HANDLER),
            )

            holder: list[Any] = []
            token = _stdio_child.set(holder)
            try:
                _install_stdio_child_hook()
                stdio, write = await stack.enter_async_context(
                    stdio_client(server_params, errlog=kwargs.get('errlog')))
            finally:
                _stdio_child.reset(token)
            if holder:
                self._stdio_children[server_name] = holder[-1]
            session_kwargs = session_kwargs or {}
            read_timeout = max(
                session_kwargs.pop('read_timeout_seconds', timeout), 1)
            # The url branch above has always passed this; stdio never did, so
            # a child that accepted the pipe and then went quiet left every
            # request on it waiting forever.
            session = await stack.enter_async_context(
                ClientSession(
                    stdio,
                    write,
                    read_timeout_seconds=_session_read_timeout(read_timeout),
                    **session_kwargs))
        else:
            raise ValueError(
                "'url' or 'command' parameter is required for connection")

        self.startup_phases[server_name] = 'initialize'
        await session.initialize()
        return session

    async def _own_server(
        self,
        server_name: str,
        kwargs: Dict[str, Any],
        ready: 'asyncio.Future',
        shutdown: asyncio.Event,
    ) -> None:
        """Hold one server's transport open for as long as it is connected.

        The anyio streams underneath ``stdio_client`` / ``streamablehttp_client``
        carry a cancel scope that must be exited by the same task that entered
        it. Handing the open context back to the caller therefore only works
        while connect and cleanup happen in one task — the moment servers are
        brought up concurrently, teardown raises "Attempted to exit cancel
        scope in a different task". Keeping open, serve and close inside this
        one task removes that coupling entirely.
        """
        _protect_transport_logs()
        diagnostic_token = _MCP_TRANSPORT_CONTEXT.set(True)
        stack = AsyncExitStack()
        try:
            async with stack:
                errlog = stack.enter_context(
                    tempfile.TemporaryFile(
                        mode='w+', encoding='utf-8', errors='replace'))
                try:
                    session = await self._open_session(
                        stack, server_name, errlog=errlog, **kwargs)
                    self.startup_phases[server_name] = 'list_tools'
                    response = await session.list_tools()
                except Exception as exc:
                    errlog.seek(0)
                    # Keep meaningful error lines even when a banner follows.
                    stderr = errlog.read(16384)
                    lines = stderr.splitlines()
                    errors = [
                        line for line in lines
                        if re.search(r'error|failed|403|401|denied|not found',
                                     line, re.I)
                    ]
                    detail = safe_mcp_error(exc, kwargs)
                    if lines:
                        detail += ' — stderr: ' + safe_mcp_error(
                            RuntimeError('\n'.join(errors or lines[-6:])),
                            kwargs)
                    raise _MCPStartupError(detail) from None
                self._initial_tools[server_name] = response
                self.sessions[server_name] = session
                if not ready.done():
                    ready.set_result(server_name)
                await shutdown.wait()
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(
                    exc if isinstance(exc, asyncio.CancelledError) else
                    _MCPStartupError(safe_mcp_error(exc, kwargs)))
            elif not isinstance(exc, asyncio.CancelledError):
                log = logger.debug if _is_teardown_noise(exc) else logger.warning
                log('MCP server %s closed: %s', server_name,
                    safe_mcp_error(exc, kwargs))
        finally:
            self.sessions.pop(server_name, None)
            self._initial_tools.pop(server_name, None)
            _MCP_TRANSPORT_CONTEXT.reset(diagnostic_token)

    async def connect_to_server(self,
                                server_name: str,
                                timeout: int = CONNECTION_TIMEOUT,
                                startup_timeout: Optional[float] = None,
                                **kwargs):
        if self.is_connected(server_name):
            return server_name
        if startup_timeout is None:
            startup_timeout = (DEFAULT_SERVER_STARTUP_TIMEOUT
                               if kwargs.get('command') and not kwargs.get('url')
                               else MCP_PROBE_TIMEOUT)
        try:
            budget = float(startup_timeout)
        except (TypeError, ValueError):
            raise ValueError(
                'startup_timeout must be a positive finite number') from None
        if (isinstance(startup_timeout, bool) or not math.isfinite(budget)
                or budget <= 0):
            raise ValueError(
                'startup_timeout must be a positive finite number')
        startup_timeout = budget
        if server_name in self._server_tasks:
            await self._stop_server(server_name, graceful=False)
        self.startup_failures.pop(server_name, None)
        logger.info(f'connect to {server_name}')
        ready: 'asyncio.Future' = asyncio.get_running_loop().create_future()
        # Retrieve as soon as the owner stores an exception, including the
        # CancelledError a quit leaves behind after the waiter has moved on.
        ready.add_done_callback(_retrieve_future)
        shutdown = asyncio.Event()
        task = asyncio.create_task(
            self._own_server(server_name, {
                'timeout': timeout,
                **kwargs
            }, ready, shutdown),
            name=f'mcp-server:{server_name}')
        self._track_task(task)
        self._server_tasks[server_name] = task
        self._server_shutdown[server_name] = shutdown
        self._server_ready[server_name] = ready
        try:
            await asyncio.wait_for(asyncio.shield(ready), startup_timeout)
        except BaseException as exc:
            # Cancel the readiness future BEFORE stopping the owner, otherwise
            # its late failure becomes an unobserved Future exception.
            ready.cancel()
            phase = self.startup_phases.get(server_name, 'connect')
            if not isinstance(exc, asyncio.CancelledError):
                reason = (f'{phase} timed out after {startup_timeout:g}s'
                          if isinstance(exc,
                                        (asyncio.TimeoutError, TimeoutError))
                          else f'{phase}: {safe_mcp_error(exc, kwargs)}')
                self.startup_failures[server_name] = reason
            await self._stop_server(server_name, graceful=False)
            if isinstance(exc, TimeoutError):
                raise TimeoutError(self.startup_failures[server_name]) from None
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise _MCPStartupError(self.startup_failures[server_name]) from None
        self._server_ready.pop(server_name, None)
        return server_name

    async def _stop_server(self,
                           server_name: str,
                           graceful: bool = True) -> None:
        """Ask a server's owner task to close its transport, and wait for it."""
        shutdown = self._server_shutdown.get(server_name)
        task = self._server_tasks.get(server_name)
        ready = self._server_ready.get(server_name)
        self.sessions.pop(server_name, None)
        self._initial_tools.pop(server_name, None)
        if shutdown is not None:
            shutdown.set()
        if task is None:
            _retrieve_future(ready)
            return
        try:
            if graceful and not task.done():
                try:
                    await asyncio.wait({task}, timeout=SERVER_STOP_TIMEOUT)
                except asyncio.CancelledError:
                    # Preserve the TUI quit contract: let the owner close its
                    # own cancel scope, but never wait indefinitely.
                    await asyncio.wait({task}, timeout=SERVER_STOP_TIMEOUT)
            if not task.done():
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=SERVER_STOP_TIMEOUT)
                if not done:
                    # Retain ownership so shutdown/reconnect can retry cleanup.
                    raise RuntimeError(f'MCP {server_name} cleanup timed out')
        finally:
            if task.done():
                self._server_tasks.pop(server_name, None)
                self._server_shutdown.pop(server_name, None)
                self._server_ready.pop(server_name, None)
                self._stdio_children.pop(server_name, None)
            _retrieve_future(task)
            _retrieve_future(ready)

    def _plan_server(self, name: str, server: Dict[str, Any],
                     default_timeout: int) -> Dict[str, Any]:
        """Pull the keys ``connect_to_server`` does not take out of a server
        block, and resolve its env against the ambient one."""
        server = copy.deepcopy(server)
        env_dict = self.resolve_server_env(server)
        server.pop('env', None)
        if server.get('startup_timeout') is None:
            server.pop('startup_timeout', None)
        self.exclude_functions.pop(name, None)
        self.include_functions.pop(name, None)
        if 'exclude' in server:
            self.exclude_functions[name] = server.pop('exclude')
        if 'include' in server:
            self.include_functions[name] = server.pop('include')
        if self.include_functions.get(name) and self.exclude_functions.get(
                name):
            raise ValueError('Set either include or exclude, not both')
        for key in ('enabled', 'source', 'plugin_id', 'meta', '_scope'):
            server.pop(key, None)
        return {
            'server_name': name,
            'env': env_dict,
            'timeout': server.pop('timeout', default_timeout),
            **server,
        }

    async def connect(
        self,
        timeout: int = CONNECTION_TIMEOUT,
        startup_timeout: float = DEFAULT_SERVER_STARTUP_TIMEOUT,
        failure_policy: Literal['raise_if_all_failed',
                                'skip'] = 'raise_if_all_failed',
    ) -> List[tuple]:
        """Prepare enabled servers concurrently, including their first tool list.

        Each server's budget starts after it gets a concurrency slot. Callers
        treating MCP as optional can skip even an all-failed result. Cancellation
        always propagates. Business tool calls are never automatically replayed.
        """
        if failure_policy not in ('raise_if_all_failed', 'skip'):
            raise ValueError('Unknown MCP failure_policy')
        servers = self.mcp_config.get('mcpServers', {})
        limiter = asyncio.Semaphore(max(1, MAX_PARALLEL_CONNECTS))

        async def one(name, server):
            if isinstance(server, dict) and not server.get('enabled', True):
                return None
            async with limiter:
                try:
                    plan = self._plan_server(name, server, timeout)
                    plan.setdefault('startup_timeout', startup_timeout)
                    await self.connect_to_server(**plan)
                except Exception as exc:
                    self.startup_failures.setdefault(
                        name,
                        safe_mcp_error(
                            exc, server if isinstance(server, dict) else {}))
                    return name, _MCPStartupError(self.startup_failures[name])
            return None

        try:
            results = await asyncio.gather(*(one(n, s)
                                             for n, s in servers.items()))
        except asyncio.CancelledError:
            await self.cleanup()
            raise
        failures = [result for result in results if result is not None]
        for name, _ in failures:
            logger.warning('MCP server %s unavailable: %s', name,
                           self.startup_failures[name])
        if failures and not self.sessions and failure_policy == 'raise_if_all_failed':
            name, exc = failures[0]
            raise RuntimeError(
                f'Connect {name} failed: {self.startup_failures[name]}'
            ) from None
        return failures

    async def add_mcp_config(self, mcp_config: Dict[str, Dict[str, Any]]):
        if mcp_config is None:
            return
        servers = self.mcp_config.setdefault('mcpServers', {})
        for name, server in mcp_config.get('mcpServers', {}).items():
            if name in servers and servers[
                    name] == server and self.is_connected(name):
                continue
            await self.disconnect_server(name)
            servers[name] = copy.deepcopy(server)
            if server.get('enabled', True):
                await self.connect_single_server(name, server)

    async def _reap_live_tasks(self) -> None:
        """Stop owner tasks that a cancelled connect did not finish awaiting.

        Quit during a probe used to leave those tasks for the loop shutdown,
        which then printed ``CancelledError`` after bye.
        """
        # A server nobody has signalled yet is still inside connect. Cancel
        # it. One whose shutdown event is already set is closing itself;
        # cancelling that owner exits its anyio scope in the wrong task.
        for name, task in list(self._server_tasks.items()):
            if task.done():
                continue
            shutdown = self._server_shutdown.get(name)
            if shutdown is None or not shutdown.is_set():
                task.cancel()
        pending = {task for task in self._live_tasks if not task.done()}
        if pending:
            _, pending = await asyncio.wait(pending, timeout=SERVER_STOP_TIMEOUT)
            for task in pending:
                task.cancel()
            if pending:
                _, pending = await asyncio.wait(pending, timeout=SERVER_STOP_TIMEOUT)
        for name, task in list(self._server_tasks.items()):
            if task.done():
                self._server_tasks.pop(name, None)
                self._server_shutdown.pop(name, None)
                _retrieve_future(self._server_ready.pop(name, None))
                self._stdio_children.pop(name, None)
                self.sessions.pop(name, None)
                self._initial_tools.pop(name, None)
        if pending:
            raise RuntimeError('MCP cleanup timed out; owner tasks remain tracked')

    async def cleanup(self):
        """Clean up resources"""
        try:
            for name in list(self._server_tasks):
                try:
                    # Not initialized yet: there is no session to drain, and
                    # the grace period would hang bye on the probe that just
                    # timed out.
                    established = name in self.sessions
                    await self.disconnect_server(name, graceful=established)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.debug(
                        'MCP disconnect %s during cleanup',
                        name,
                        exc_info=True)
        finally:
            await self._reap_live_tasks()
            with suppress(BaseException):
                await self.exit_stack.aclose()

    async def __aenter__(self) -> 'MCPClient':
        try:
            await self.connect()
            return self
        except Exception:
            await self.cleanup()
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.cleanup()
