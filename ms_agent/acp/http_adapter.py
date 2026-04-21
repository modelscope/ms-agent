import asyncio
import os
from typing import Any

import json
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from ms_agent.acp.server import MSAgentACPServer
from ms_agent.utils.logger import get_logger
from pydantic import BaseModel

logger = get_logger()

router = APIRouter(prefix='/api/acp', tags=['ACP Internal API'])


class RPCRequest(BaseModel):
    jsonrpc: str = '2.0'
    id: int | str | None = None
    method: str
    params: dict = {}


# Module-level server instance; set by ``configure_http_adapter``.
_server = None
_api_key: str | None = None


def configure_http_adapter(
    config_path: str,
    trust_remote_code: bool = False,
    max_sessions: int = 8,
    session_timeout: int = 3600,
    api_key: str | None = None,
) -> APIRouter:
    """Initialise the module-level ACP server and return the router.

    Call this before mounting the router into a FastAPI app.
    """
    global _server, _api_key

    _server = MSAgentACPServer(
        config_path=config_path,
        trust_remote_code=trust_remote_code,
        max_sessions=max_sessions,
        session_timeout=session_timeout,
    )
    _api_key = api_key or os.environ.get('MS_AGENT_ACP_API_KEY')

    _DummyConn.server = _server
    _server.on_connect(_DummyConn())

    return router


class _DummyConn:
    """Minimal stand-in for the SDK ``ClientSideConnection``.

    When the server runs over stdio the SDK provides a real connection
    object. Over HTTP we intercept ``session_update`` calls and
    stream them back as SSE events instead.
    """
    server = None

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}

    def get_queue(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    async def session_update(self, session_id: str, update: Any,
                             **kwargs) -> None:
        q = self.get_queue(session_id)
        data = update.model_dump(
            by_alias=True) if hasattr(update, 'model_dump') else update
        await q.put(data)

    async def request_permission(self, session_id: str, tool_call: Any,
                                 options: list, **kwargs) -> Any:
        allow = next(
            (o for o in options if 'allow' in (getattr(o, 'kind', '') or '')),
            None,
        )
        if allow:
            from types import SimpleNamespace
            return SimpleNamespace(
                outcome={
                    'outcome': 'selected',
                    'id': getattr(allow, 'option_id', 'allow_once')
                })
        from types import SimpleNamespace
        return SimpleNamespace(outcome={'outcome': 'cancelled'})


def _check_api_key(authorization: str | None = Header(None)):
    """Simple bearer-token authentication for the internal API."""
    if _api_key is None:
        return
    if not authorization:
        raise HTTPException(401, 'Authorization header required')
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer' or parts[1] != _api_key:
        raise HTTPException(403, 'Invalid API key')


@router.post('/rpc')
async def rpc_endpoint(
        req: RPCRequest,
        _auth: None = Depends(_check_api_key),
):
    """Single JSON-RPC endpoint for all ACP methods.

    For ``session/prompt`` the response is SSE; for everything else
    it is a regular JSON response.
    """
    if _server is None:
        raise HTTPException(503, 'ACP server not initialised')

    method = req.method
    params = req.params
    rpc_id = req.id

    try:
        if method == 'initialize':
            result = await _server.initialize(
                protocol_version=params.get('protocolVersion', 1), )
            return _jsonrpc_ok(rpc_id, result)

        elif method == 'session/new':
            result = await _server.new_session(
                cwd=params.get('cwd', '/tmp'),
                mcp_servers=params.get('mcpServers', []),
            )
            return _jsonrpc_ok(rpc_id, result)

        elif method == 'session/list':
            result = await _server.list_sessions(
                cursor=params.get('cursor'),
                cwd=params.get('cwd'),
            )
            return _jsonrpc_ok(rpc_id, result)

        elif method == 'session/load':
            result = await _server.load_session(
                cwd=params.get('cwd', '/tmp'),
                session_id=params.get('sessionId', ''),
            )
            return _jsonrpc_ok(rpc_id, result)

        elif method == 'session/prompt':
            return await _handle_prompt_sse(rpc_id, params)

        elif method == 'session/cancel':
            await _server.cancel(session_id=params.get('sessionId', ''))
            return JSONResponse({
                'jsonrpc': '2.0',
                'id': rpc_id,
                'result': None
            })

        elif method == 'session/setConfigOption':
            result = await _server.set_config_option(
                config_id=params.get('configId', ''),
                session_id=params.get('sessionId', ''),
                value=params.get('value', ''),
            )
            return _jsonrpc_ok(rpc_id, result)

        else:
            return JSONResponse(
                {
                    'jsonrpc': '2.0',
                    'id': rpc_id,
                    'error': {
                        'code': -32601,
                        'message': f'Method not found: {method}'
                    }
                },
                status_code=200,
            )

    except Exception as e:
        from ms_agent.acp.errors import wrap_agent_error, ACPError
        rpc_err = wrap_agent_error(e)
        return JSONResponse(
            {
                'jsonrpc': '2.0',
                'id': rpc_id,
                'error': {
                    'code': rpc_err.code,
                    'message': rpc_err.message,
                    'data': getattr(rpc_err, 'data', None)
                }
            },
            status_code=200,
        )


async def _handle_prompt_sse(rpc_id, params):
    """Run a prompt and stream updates as SSE events."""
    from acp import text_block as tb
    session_id = params.get('sessionId', '')
    prompt_blocks = params.get('prompt', [])

    acp_blocks = []
    for b in prompt_blocks:
        if isinstance(b, dict) and b.get('type') == 'text':
            acp_blocks.append(tb(b['text']))
        else:
            acp_blocks.append(tb(str(b)))

    conn = _server.connection
    q = conn.get_queue(session_id)

    async def event_stream():
        prompt_task = asyncio.create_task(
            _server.prompt(
                prompt=acp_blocks,
                session_id=session_id,
            ))
        try:
            while not prompt_task.done():
                try:
                    update = await asyncio.wait_for(q.get(), timeout=0.5)
                    yield f'data: {json.dumps(update, default=str)}\n\n'
                except asyncio.TimeoutError:
                    continue

            while not q.empty():
                update = q.get_nowait()
                yield f'data: {json.dumps(update, default=str)}\n\n'

            result = prompt_task.result()
            final = result.model_dump(
                by_alias=True) if hasattr(result, 'model_dump') else result
            response = {'jsonrpc': '2.0', 'id': rpc_id, 'result': final}
            yield f'data: {json.dumps(response, default=str)}\n\n'

        except Exception as e:
            from ms_agent.acp.errors import wrap_agent_error
            rpc_err = wrap_agent_error(e)
            err_resp = {
                'jsonrpc': '2.0',
                'id': rpc_id,
                'error': {
                    'code': rpc_err.code,
                    'message': rpc_err.message
                }
            }
            yield f'data: {json.dumps(err_resp)}\n\n'

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


def _jsonrpc_ok(rpc_id, result) -> JSONResponse:
    data = result.model_dump(
        by_alias=True) if hasattr(result, 'model_dump') else result
    return JSONResponse({'jsonrpc': '2.0', 'id': rpc_id, 'result': data})
