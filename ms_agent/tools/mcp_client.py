from __future__ import annotations

# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import base64
import contextvars
import copy
import inspect
import json
import mimetypes
import os
import re
import shutil
import uuid
from contextlib import AsyncExitStack, suppress
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
from ms_agent.utils import enhance_error, get_logger

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

#: Wall-clock ceiling on bringing ONE server up (spawn/dial + initialize).
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
    'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'TMPDIR', 'TERM', 'TZ',
    'LANG', 'LC_ALL', 'LC_CTYPE',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
    # ALL_PROXY is deliberately absent: a socks5:// value makes any child
    # whose httpx lacks the socksio extra fail on its FIRST request, and the
    # child's venv is not ours to fix. The scheme-specific variables cover
    # the download-acceleration need without that trap.
    'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
    'http_proxy', 'https_proxy', 'no_proxy',
    'UV_INDEX_URL', 'UV_DEFAULT_INDEX', 'PIP_INDEX_URL',
    'npm_config_registry',
)

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
    searched = ':'.join([os.environ.get('PATH', '')] +
                        list(_STDIO_EXTRA_BIN_DIRS))
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
    return ('the arguments were rejected by the tool:\n'
            + '\n'.join(lines)
            + '\nSend each value as its declared JSON type (a number '
            'unquoted, not as a string) and call again.\n\nOriginal error:\n'
            + _PYDANTIC_DOC_LINK.sub('', detail).strip())


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
            response = await session.list_tools()
        except Exception as e:
            new_eg = enhance_error(
                e, f'MCP `{server_name}` list tool failed, details: ')
            raise new_eg from e
        # Logged from here rather than from connect(): the same listing that
        # registers the tools also reports them, so the log costs no extra
        # round trip to the server.
        self.print_tools(server_name, response)
        return self._filter_session_tools(server_name, response)

    async def get_tools(self) -> Dict:
        tools: Dict[str, List[Tool]] = {}
        for key in self.sessions:
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
        env_dict = copy.deepcopy(server.get('env') or {})
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
        server = copy.deepcopy(server_config)
        env_dict = self.resolve_server_env(server)
        if 'exclude' in server:
            self.exclude_functions[server_name] = server.pop('exclude')
        if 'include' in server:
            self.include_functions[server_name] = server.pop('include')
        assert (not self.include_functions.get(server_name)) or (
            not self.exclude_functions.get(server_name)
        ), 'Set either `include` or `exclude` in tools config.'
        timeout = server.pop('timeout', timeout)
        for drop_key in ('enabled', 'source', 'plugin_id', 'meta'):
            server.pop(drop_key, None)
        return await self.connect_to_server(
            server_name=server_name,
            env=env_dict,
            timeout=timeout,
            startup_timeout=startup_timeout,
            **server,
        )

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
        session_kwargs = kwargs.get('session_kwargs')
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
            args = kwargs.get('args')
            if not args:
                raise ValueError(
                    "'args' parameter is required for stdio connection")
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
                    stdio_client(server_params))
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
        stack = AsyncExitStack()
        try:
            async with stack:
                session = await self._open_session(stack, server_name, **kwargs)
                self.sessions[server_name] = session
                if not ready.done():
                    ready.set_result(server_name)
                await shutdown.wait()
        except BaseException as exc:  # noqa: BLE001
            if not ready.done():
                ready.set_exception(exc)
            elif isinstance(exc, asyncio.CancelledError):
                pass
            elif _is_teardown_noise(exc):
                logger.debug('MCP server %s closed: %s', server_name, exc)
            else:
                logger.warning('MCP server %s dropped: %s', server_name, exc)
        finally:
            self.sessions.pop(server_name, None)

    async def connect_to_server(self,
                                server_name: str,
                                timeout: int = CONNECTION_TIMEOUT,
                                startup_timeout: Optional[float] = None,
                                **kwargs):
        if self.is_connected(server_name):
            return server_name
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
            if startup_timeout:
                # Shield so a timeout stops US waiting without cancelling the
                # owner mid-open; _stop_server below unwinds it in its own task.
                await asyncio.wait_for(
                    asyncio.shield(ready), timeout=startup_timeout)
            else:
                await ready
        except BaseException:
            # It never came up, so there is no established session to shut down
            # politely — waiting out the grace period here would just add it to
            # the startup timeout the caller already spent.
            await self._stop_server(server_name, graceful=False)
            raise
        self._server_ready.pop(server_name, None)
        return server_name

    async def _stop_server(self,
                           server_name: str,
                           graceful: bool = True) -> None:
        """Ask a server's owner task to close its transport, and wait for it."""
        self._stdio_children.pop(server_name, None)
        shutdown = self._server_shutdown.pop(server_name, None)
        task = self._server_tasks.pop(server_name, None)
        ready = self._server_ready.pop(server_name, None)
        self.sessions.pop(server_name, None)
        if shutdown is not None:
            shutdown.set()
        if task is None or task.done():
            _retrieve_future(task)
            _retrieve_future(ready)
            return
        if graceful:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), timeout=SERVER_STOP_TIMEOUT)
                _retrieve_future(ready)
                return
            except asyncio.TimeoutError:
                logger.debug('MCP server %s stop timed out', server_name)
                _retrieve_future(ready)
            except asyncio.CancelledError:
                # The TUI generator is closing. The owner already has the
                # shutdown signal — wait it out. Cancelling it here would
                # athrow() streamablehttp_client from the wrong task.
                with suppress(BaseException):
                    await asyncio.shield(task)
                _retrieve_future(ready)
                return
            except BaseException as exc:  # noqa: BLE001
                logger.debug('MCP server %s stopped with %s', server_name, exc)
                _retrieve_future(ready)
                return
        task.cancel()
        with suppress(BaseException):
            await task
        _retrieve_future(task)
        _retrieve_future(ready)

    def _plan_server(self, name: str, server: Dict[str, Any],
                     default_timeout: int) -> Dict[str, Any]:
        """Pull the keys ``connect_to_server`` does not take out of a server
        block, and resolve its env against the ambient one."""
        envs = Env.load_env()
        env_dict = server.pop('env', {})
        env_dict = {
            key: value if value else envs.get(key, '')
            for key, value in env_dict.items()
        }
        if 'exclude' in server:
            self.exclude_functions[name] = server.pop('exclude')
        if 'include' in server:
            self.include_functions[name] = server.pop('include')
        assert (not self.include_functions.get(name)) or (
            not self.exclude_functions.get(name)
        ), 'Set either `include` or `exclude` in tools config.'
        # Bound to THIS server. Assigning it to the shared default (as the
        # sequential loop used to) leaked one server's timeout onto every
        # server configured after it.
        return {
            'server_name': name,
            'env': env_dict,
            'timeout': server.pop('timeout', default_timeout),
            **server,
        }

    async def connect(
        self,
        timeout: int = CONNECTION_TIMEOUT,
        startup_timeout: int = DEFAULT_SERVER_STARTUP_TIMEOUT,
    ) -> List[tuple]:
        """Bring every configured server up, and report which ones did not.

        Servers are started TOGETHER rather than one after another. Startup
        cost is dominated by what is being started — a cold ``uvx`` resolving
        and downloading its package runs to seconds — and paying that in
        sequence multiplied it by the number of servers before the user's
        first message could even be read.

        A server that fails or exceeds ``startup_timeout`` is left out instead
        of taking the rest down with it; the returned ``(name, exc)`` list lets
        a caller surface exactly what is missing. If NOTHING came up the
        failure is raised, since that is indistinguishable from a broken
        configuration and callers rely on hearing about it.
        """
        assert self.mcp_config, 'MCP config is required'
        mcp_config = self.mcp_config['mcpServers']
        plans = [
            self._plan_server(name, server, timeout)
            for name, server in mcp_config.items()
        ]
        if not plans:
            return []

        limiter = asyncio.Semaphore(MAX_PARALLEL_CONNECTS)

        async def _one(plan: Dict[str, Any]):
            async with limiter:
                # The bound is applied inside connect_to_server, which unwinds
                # a server that overran through its own owner task.
                await self.connect_to_server(
                    startup_timeout=startup_timeout, **plan)

        results = await asyncio.gather(
            *(_one(plan) for plan in plans), return_exceptions=True)

        failures: List[tuple] = []
        for plan, result in zip(plans, results):
            if not isinstance(result, BaseException):
                continue
            name = plan['server_name']
            if isinstance(result, asyncio.TimeoutError):
                result = TimeoutError(
                    f'MCP server `{name}` did not finish starting within '
                    f'{startup_timeout}s (set MCP_STARTUP_TIMEOUT to change). '
                    'A launcher such as uvx/npx populating a cold cache, or an '
                    'unreachable upstream, is the usual cause.')
            failures.append((name, result))

        if failures and not self.sessions:
            name, exc = failures[0]
            new_eg = enhance_error(exc, f'Connect `{name}` failed, details:')
            raise new_eg from exc
        for name, exc in failures:
            logger.warning('MCP server %s unavailable this session: %s', name,
                           exc)
        return failures

    async def add_mcp_config(self, mcp_config: Dict[str, Dict[str, Any]]):
        if mcp_config is None:
            return
        new_mcp_config = mcp_config.get('mcpServers', {})
        servers = self.mcp_config.setdefault('mcpServers', {})
        envs = Env.load_env()
        for name, server in new_mcp_config.items():
            if name in servers and servers[name] == server:
                continue
            else:
                servers[name] = server
                env_dict = server.pop('env', {})
                env_dict = {
                    key: value if value else envs.get(key, '')
                    for key, value in env_dict.items()
                }
                if 'exclude' in server:
                    self.exclude_functions[name] = server.pop('exclude')
                await self.connect_to_server(
                    server_name=name, env=env_dict, **server)
        self.mcp_config['mcpServers'].update(new_mcp_config)

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
        pending = [task for task in list(self._live_tasks) if not task.done()]
        readies = list(self._server_ready.values())
        self._server_tasks.clear()
        self._server_shutdown.clear()
        self._server_ready.clear()
        self.sessions.clear()
        try:
            if pending:
                await asyncio.shield(
                    asyncio.gather(*pending, return_exceptions=True))
        except asyncio.CancelledError:
            return
        finally:
            for task in pending:
                _retrieve_future(task)
            for ready in readies:
                _retrieve_future(ready)

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
