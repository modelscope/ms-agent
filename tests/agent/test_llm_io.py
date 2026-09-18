"""Model I/O must not starve other tasks, including before response headers."""
import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import openai
import pytest
from omegaconf import OmegaConf

from ms_agent.agent.llm_agent import LLMAgent
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


def make_agent(handler, stream=True, legacy=False, protocol='openai'):
    config = OmegaConf.create({
        'llm': {'model': 'probe'}, 'generation_config': {'stream': stream}
    })
    if protocol == 'anthropic':
        anthropic = pytest.importorskip('anthropic')
        from ms_agent.llm.anthropic_llm import Anthropic
        from ms_agent.llm.transport.anthropic_messages import (
            AnthropicMessagesTransport)
        if legacy:
            llm = Anthropic(config, api_key='local-test',
                            base_url='http://model.test/v1')
        else:
            llm = AnthropicMessagesTransport(
                model='probe', api_key='local-test',
                base_url='http://model.test/v1',
                generation_config={'stream': stream})
        client_cls = anthropic.Anthropic
    elif legacy:
        llm = LegacyOpenAI(OmegaConf.create({
            'llm': {'model': 'probe'}, 'generation_config': {'stream': stream}
        }), api_key='local-test', base_url='http://model.test/v1')
        client_cls = openai.OpenAI
    else:
        llm = OpenAICompatTransport(
            model='probe', api_key='local-test', base_url='http://model.test/v1',
            generation_config={'stream': stream})
        client_cls = openai.OpenAI
    llm.client.close()
    llm.client = client_cls(
        api_key='local-test', base_url='http://model.test/v1', max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
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


async def run_step(agent):
    # Test the real step body without unrelated retry/backoff policy.
    return [rows async for rows in LLMAgent.step.__wrapped__(
        agent, [Message(role='user', content='Respond with OK')])]


async def reached(event):
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 5), 6)


def response(body):
    return httpx.Response(200, headers={
        'Content-Type': 'text/event-stream' if body.stream else 'application/json'
    }, stream=body)


@pytest.mark.parametrize('stream', [True, False])
@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_first_request_leaves_event_loop_responsive(stream, legacy, protocol):

    async def check():
        entered, release = threading.Event(), threading.Event()
        body = ResponseBody(stream, protocol=protocol)
        request_threads = []

        def handle(request):
            request_threads.append(threading.get_ident())
            entered.set()
            assert release.wait(10), 'test did not release response headers'
            return response(body)

        agent = make_agent(handle, stream, legacy=legacy, protocol=protocol)
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(entered)
            assert request_threads[0] != threading.get_ident()
            assert not task.done()
            # A separate coroutine runs while the HTTP request is still waiting.
            tick = asyncio.Event()
            asyncio.get_running_loop().call_soon(tick.set)
            await asyncio.wait_for(tick.wait(), .5)
            release.set()
            await asyncio.wait_for(task, 2)
            assert agent.handle_new_response.call_args.args[1].content == 'OK'
            assert body.closed.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_cancel_before_headers_closes_late_response_without_reading_body(legacy, protocol):

    async def check():
        entered, release = threading.Event(), threading.Event()
        body = ResponseBody(True, wait_for_body=True, protocol=protocol)

        def handle(request):
            entered.set()
            assert release.wait(10), 'test did not release response headers'
            return response(body)

        agent = make_agent(handle, legacy=legacy, protocol=protocol)
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(entered)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, .5)
            release.set()
            await reached(body.closed)
            assert not body.entered.is_set()
            agent.handle_new_response.assert_not_called()
        finally:
            release.set()
            body.release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_cancel_as_headers_return_does_not_lose_response_ownership(protocol):

    async def check():
        body = ResponseBody(True, wait_for_body=True, protocol=protocol)
        agent = make_agent(lambda request: response(body), protocol=protocol)
        original = agent.llm.generate
        loop = asyncio.get_running_loop()

        def generate(*args, **kwargs):
            result = original(*args, **kwargs)
            loop.call_soon_threadsafe(task.cancel)
            return result

        agent.llm.generate = generate
        task = asyncio.create_task(run_step(agent))
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            await reached(body.closed)
            assert not body.entered.is_set()
        finally:
            body.release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_cancel_during_stream_read_interrupts_and_closes_iterator(legacy, protocol):

    async def check():
        body = ResponseBody(True, wait_for_body=True, protocol=protocol)
        agent = make_agent(lambda request: response(body), legacy=legacy,
                           protocol=protocol)
        iterator_closed = threading.Event()
        generate = agent.llm.generate

        def tracked_generate(*args, **kwargs):
            chunks = generate(*args, **kwargs)

            def tracked_chunks():
                try:
                    yield from chunks
                finally:
                    chunks.close()
                    iterator_closed.set()

            return tracked_chunks()

        agent.llm.generate = tracked_generate
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(body.entered)
            assert body.reader_thread != threading.get_ident()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, .5)
            await reached(body.closed)
            # Cancellation returns before the worker; wait for its iterator's
            # finally block as well as the immediate HTTP-response close.
            await reached(iterator_closed)
            assert agent.llm._active_stream is None
            agent.handle_new_response.assert_not_called()
        finally:
            body.release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_request_timeout_propagates_without_blocking_event_loop(protocol):

    async def check():
        entered, release = threading.Event(), threading.Event()
        request_threads = []

        def handle(request):
            request_threads.append(threading.get_ident())
            entered.set()
            assert release.wait(10), 'test did not release request timeout'
            raise httpx.ReadTimeout('simulated timeout', request=request)

        agent = make_agent(handle, protocol=protocol)
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(entered)
            assert request_threads[0] != threading.get_ident()
            release.set()
            with pytest.raises((openai if protocol == 'openai' else
                                pytest.importorskip('anthropic')).APITimeoutError):
                await asyncio.wait_for(task, 2)
            agent.handle_new_response.assert_not_called()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_cancelled_request_cleanup_does_not_interrupt_replacement_llm(protocol):
    """Reusing an SDK agent after cancellation can install a new transport."""

    async def check():
        entered, release = threading.Event(), threading.Event()
        body = ResponseBody(True, wait_for_body=True, protocol=protocol)

        def handle(request):
            entered.set()
            assert release.wait(10)
            return response(body)

        agent = make_agent(handle, protocol=protocol)
        original_llm = agent.llm
        replacement = Mock()
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(entered)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            # run() prepares a new LLM on the next invocation. The abandoned
            # worker still owns the old transport, never this replacement.
            agent.llm = replacement
            release.set()
            await reached(body.closed)
            replacement.interrupt.assert_not_called()
            assert body.closed.is_set()
        finally:
            release.set()
            body.release.set()
            await asyncio.gather(task, return_exceptions=True)
            original_llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('wait_for_body', [False, True])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
def test_slow_model_does_not_starve_host_executor(wait_for_body, protocol):
    """Session storage must still run when all model workers are waiting."""

    async def check():
        entered, release = threading.Event(), threading.Event()
        body = ResponseBody(True, wait_for_body=wait_for_body, protocol=protocol)

        def handle(request):
            entered.set()
            if not wait_for_body:
                assert release.wait(10)
            return response(body)

        agent = make_agent(handle, protocol=protocol)
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        task = asyncio.create_task(run_step(agent))
        try:
            target = body.entered if wait_for_body else entered
            async def wait_for_request():
                while not target.is_set():
                    await asyncio.sleep(.01)
            await asyncio.wait_for(wait_for_request(), 3)
            assert await asyncio.wait_for(
                asyncio.to_thread(lambda: 'session storage'), .5
            ) == 'session storage'
        finally:
            release.set()
            body.release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    asyncio.run(check())


@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('legacy', [False, True])
def test_cancel_stalled_tcp_read_releases_model_worker(monkeypatch, protocol,
                                                       legacy):
    """A real blocked socket must exit; a mock close that releases an Event
    cannot detect cross-thread close() leaving recv() alive until timeout.
    """
    from ms_agent.llm import io

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

    async def check():
        agent = make_agent(lambda r: None, legacy=legacy, protocol=protocol)
        client_cls = type(agent.llm.client)
        agent.llm.client.close()
        agent.llm.client = client_cls(
            api_key='local-test',
            base_url=f'http://127.0.0.1:{server.server_port}',
            max_retries=0, timeout=2,
            http_client=httpx.Client(event_hooks={'response': [mark_response]}))
        task = asyncio.create_task(run_step(agent))
        try:
            await reached(reading)
            # Give the worker time to enter recv(), not just the stream wrapper.
            await asyncio.sleep(.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, .5)
            assert await asyncio.wait_for(
                io.run_in_llm_executor(lambda: 'next request'), .5
            ) == 'next request'
            assert not release.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            agent.llm.client.close()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            monkeypatch.setattr(io, '_executor', pool)
            asyncio.run(check())
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize('http_version,closed', [('HTTP/2', False),
                                               ('HTTP/1.1', True)])
def test_interrupt_preserves_shared_or_released_connection(http_version, closed):
    from ms_agent.llm.io import interrupt_stream

    network = Mock()
    response = httpx.Response(
        200, stream=ResponseBody(True),
        extensions={'http_version': http_version.encode(),
                    'network_stream': network})
    if closed:
        response.close()
    stream = SimpleNamespace(response=response, close=Mock())
    interrupt_stream(stream)
    network.get_extra_info.assert_not_called()
    stream.close.assert_called_once()
