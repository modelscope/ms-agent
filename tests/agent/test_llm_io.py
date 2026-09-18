"""Model I/O must not starve other tasks, including before response headers."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import wraps
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import openai
import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.llm import io
from ms_agent.llm.openai_llm import OpenAI as LegacyOpenAI
from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.utils import Message


class ResponseBody(httpx.SyncByteStream):

    def __init__(self, stream, *, wait_for_body=False, protocol='openai'):
        self.stream = stream
        self.protocol = protocol
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = threading.Event()
        self.reader_thread = None
        if not wait_for_body:
            self.release.set()

    def __iter__(self):
        self.reader_thread = threading.get_ident()
        self.entered.set()
        assert self.release.wait(10), 'test did not release response body'
        if self.protocol == 'anthropic':
            message = {
                'id': 'probe', 'type': 'message', 'role': 'assistant',
                'model': 'probe', 'content': [], 'stop_reason': None,
                'stop_sequence': None,
                'usage': {'input_tokens': 1, 'output_tokens': 1},
            }
            if self.stream:
                events = [
                    {'type': 'message_start', 'message': message},
                    {'type': 'content_block_start', 'index': 0,
                     'content_block': {'type': 'text', 'text': ''}},
                    {'type': 'content_block_delta', 'index': 0,
                     'delta': {'type': 'text_delta', 'text': 'OK'}},
                    {'type': 'content_block_stop', 'index': 0},
                    {'type': 'message_delta',
                     'delta': {'stop_reason': 'end_turn', 'stop_sequence': None},
                     'usage': {'output_tokens': 1}},
                    {'type': 'message_stop'},
                ]
                for event in events:
                    yield (f"event: {event['type']}\ndata: "
                           + json.dumps(event) + '\n\n').encode()
            else:
                message.update(content=[{'type': 'text', 'text': 'OK'}],
                               stop_reason='end_turn')
                yield json.dumps(message).encode()
            return
        if self.stream:
            for delta, reason in [({'content': 'OK'}, None), ({}, 'stop')]:
                chunk = {
                    'id': 'probe', 'object': 'chat.completion.chunk',
                    'created': 0, 'model': 'probe',
                    'choices': [{'index': 0, 'delta': delta,
                                 'finish_reason': reason}],
                }
                yield ('data: ' + json.dumps(chunk) + '\n\n').encode()
            yield b'data: [DONE]\n\n'
        else:
            yield json.dumps({
                'id': 'probe', 'object': 'chat.completion', 'created': 0,
                'model': 'probe', 'choices': [{'index': 0,
                    'message': {'role': 'assistant', 'content': 'OK'},
                    'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1,
                          'total_tokens': 2},
            }).encode()

    def close(self):
        self.closed.set()
        self.release.set()


def make_agent(handler=None, *, stream=True, legacy=False, protocol='openai',
               base_url='http://model.test/v1', http_client=None):
    config = OmegaConf.create({
        'llm': {'model': 'probe'}, 'generation_config': {'stream': stream}})
    if protocol == 'anthropic':
        pytest.importorskip('anthropic')
        from ms_agent.llm.anthropic_llm import Anthropic
        from ms_agent.llm.transport.anthropic_messages import (
            AnthropicMessagesTransport)
        cls = Anthropic if legacy else AnthropicMessagesTransport
    else:
        cls = LegacyOpenAI if legacy else OpenAICompatTransport
    credentials = {'api_key': 'local-test', 'base_url': base_url}
    llm = (cls(config, **credentials) if legacy else cls(
        model='probe', generation_config={'stream': stream}, **credentials))
    llm.client.close()
    llm.client = type(llm.client)(
        **credentials, max_retries=0, timeout=2,
        http_client=http_client or httpx.Client(
            transport=httpx.MockTransport(handler)))
    agent = LLMAgent.__new__(LLMAgent)
    agent.llm = llm
    agent.config = OmegaConf.create({
        'generation_config': {'stream': stream, 'stream_output': False}})
    agent.task_manager = None
    agent.load_cache = False
    agent._event_sink = None
    agent.on_generate_response = AsyncMock()
    agent.tool_manager = SimpleNamespace(get_tools=AsyncMock(return_value=[]))
    agent.on_tool_call = AsyncMock()
    for method in ('log_output', 'handle_new_response', 'save_history',
                   '_emit_tool_composing', '_record_image_deliveries'):
        setattr(agent, method, Mock())
    return agent


def run_async(test):
    # Keep SDK tests independent of the WebUI's pytest-asyncio dependency.
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run


async def reached(event):
    async def wait():
        while not event.is_set():
            await asyncio.sleep(.01)
    # Do not use the executor being tested to wait for its progress.
    await asyncio.wait_for(wait(), 5)


async def cancel(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, .5)


@asynccontextmanager
async def running(agent, *releases):
    async def step():
        # Exercise the real step body without unrelated retry/backoff policy.
        return [rows async for rows in LLMAgent.step.__wrapped__(
            agent, [Message(role='user', content='Respond with OK')])]
    llm = agent.llm  # Cleanup must retain this client if a test replaces it.
    task = asyncio.create_task(step())
    try:
        yield task
    finally:
        for event in releases:
            event.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        llm.client.close()


@asynccontextmanager
async def mock_request(protocol, *, stream=True, legacy=False,
                       wait_for='headers', error=None):
    body = ResponseBody(stream, wait_for_body=True, protocol=protocol)
    request = SimpleNamespace(body=body, headers_entered=threading.Event(),
                              release_headers=threading.Event(), threads=[])
    if wait_for == 'body':
        request.release_headers.set()

    def handle(http_request):
        request.threads.append(threading.get_ident())
        request.headers_entered.set()
        assert request.release_headers.wait(10), 'headers not released'
        if error:
            raise error('simulated timeout', request=http_request)
        return httpx.Response(200, stream=body, headers={
            'Content-Type': 'text/event-stream' if stream else 'application/json'})

    request.agent = make_agent(handle, stream=stream, legacy=legacy,
                               protocol=protocol)
    async with running(request.agent, request.release_headers, body.release) as task:
        request.task = task
        yield request


@pytest.mark.parametrize('stream', [True, False])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_first_request_leaves_event_loop_responsive(stream, legacy, protocol):
    async with mock_request(protocol, stream=stream, legacy=legacy) as r:
        await reached(r.headers_entered)
        assert r.threads[0] != threading.get_ident()
        assert not r.task.done()
        tick = asyncio.Event()
        asyncio.get_running_loop().call_soon(tick.set)
        await asyncio.wait_for(tick.wait(), .5)
        r.release_headers.set()
        r.body.release.set()
        await asyncio.wait_for(r.task, 2)
        assert r.agent.handle_new_response.call_args.args[1].content == 'OK'
        assert r.body.closed.is_set()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_cancel_before_headers_closes_late_response_without_reading_body(legacy, protocol):
    async with mock_request(protocol, legacy=legacy) as r:
        await reached(r.headers_entered)
        await cancel(r.task)
        r.release_headers.set()
        await reached(r.body.closed)
        assert not r.body.entered.is_set()
        r.agent.handle_new_response.assert_not_called()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_cancel_as_headers_return_does_not_lose_response_ownership(protocol):
    async with mock_request(protocol, wait_for='body') as r:
        generate = r.agent.llm.generate
        loop = asyncio.get_running_loop()

        def cancel_on_return(*args, **kwargs):
            result = generate(*args, **kwargs)
            loop.call_soon_threadsafe(r.task.cancel)
            return result

        r.agent.llm.generate = cancel_on_return
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(r.task, 2)
        await reached(r.body.closed)
        assert not r.body.entered.is_set()


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_cancel_during_stream_read_interrupts_and_closes_iterator(legacy, protocol):
    async with mock_request(protocol, legacy=legacy, wait_for='body') as r:
        iterator_closed = threading.Event()
        generate = r.agent.llm.generate

        def tracked_generate(*args, **kwargs):
            chunks = generate(*args, **kwargs)

            def tracked_chunks():
                try:
                    yield from chunks
                finally:
                    chunks.close()
                    iterator_closed.set()
            return tracked_chunks()

        r.agent.llm.generate = tracked_generate
        await reached(r.body.entered)
        assert r.body.reader_thread != threading.get_ident()
        await cancel(r.task)
        await reached(r.body.closed)
        # Wait for the worker's iterator finally, not just HTTP close.
        await reached(iterator_closed)
        assert r.agent.llm._active_stream is None
        r.agent.handle_new_response.assert_not_called()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_request_timeout_propagates_without_blocking_event_loop(protocol):
    async with mock_request(protocol, error=httpx.ReadTimeout) as r:
        await reached(r.headers_entered)
        assert r.threads[0] != threading.get_ident()
        r.release_headers.set()
        sdk = openai if protocol == 'openai' else pytest.importorskip('anthropic')
        with pytest.raises(sdk.APITimeoutError):
            await asyncio.wait_for(r.task, 2)
        r.agent.handle_new_response.assert_not_called()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_cancelled_request_cleanup_does_not_interrupt_replacement_llm(protocol):
    async with mock_request(protocol) as r:
        await reached(r.headers_entered)
        await cancel(r.task)
        replacement = Mock()
        r.agent.llm = replacement
        r.release_headers.set()
        await reached(r.body.closed)
        replacement.interrupt.assert_not_called()


@pytest.mark.parametrize('wait_for_body', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@run_async
async def test_slow_model_does_not_starve_host_executor(wait_for_body, protocol):
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
    async with mock_request(protocol, wait_for='body' if wait_for_body else 'headers') as r:
        await reached(r.body.entered if wait_for_body else r.headers_entered)
        assert await asyncio.wait_for(
            asyncio.to_thread(lambda: 'session storage'), .5) == 'session storage'


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('legacy', [False, True])
@run_async
async def test_cancel_stalled_tcp_read_releases_model_worker(monkeypatch, protocol, legacy):
    """A mock close can release an Event while a real socket stays in recv()."""
    release, reading = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.flush()
            release.wait(5)

    class MarkRead(httpx.SyncByteStream):

        def __init__(self, inner):
            self.inner = inner

        def __iter__(self):
            reading.set()
            yield from self.inner

        def close(self):
            self.inner.close()

    def mark_response(response):
        response.stream = MarkRead(response.stream)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            monkeypatch.setattr(io, '_executor', pool)
            agent = make_agent(legacy=legacy, protocol=protocol,
                               base_url=f'http://127.0.0.1:{server.server_port}',
                               http_client=httpx.Client(event_hooks={'response': [mark_response]}))
            async with running(agent, release) as task:
                await reached(reading)
                await asyncio.sleep(.05)  # Let the worker enter recv().
                await cancel(task)
                assert await asyncio.wait_for(
                    io.run_in_llm_executor(lambda: 'next request'), .5) == 'next request'
                assert not release.is_set()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('http_version,closed', [('HTTP/2', False),
                                               ('HTTP/1.1', True)])
def test_interrupt_preserves_shared_or_released_connection(http_version, closed):
    network = Mock()
    response = httpx.Response(
        200, stream=ResponseBody(True),
        extensions={'http_version': http_version.encode(), 'network_stream': network})
    if closed:
        response.close()
    stream = SimpleNamespace(response=response, close=Mock())
    io.interrupt_stream(stream)
    network.get_extra_info.assert_not_called()
    stream.close.assert_called_once()
