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
from ms_agent.llm.router import LLMProvider
from ms_agent.llm.transport.openai_compat import OpenAICompatTransport
from ms_agent.llm.utils import Message


def test_owned_response_defers_close_until_the_reader_exits():
    entered, release = threading.Event(), threading.Event()
    closed_by = []
    network = Mock()
    response = SimpleNamespace(is_closed=False, http_version='HTTP/1.1',
                               extensions={'network_stream': network})
    owned = io.OwnedResponse(SimpleNamespace(
        response=response, close=lambda: closed_by.append(threading.get_ident())))

    def read():
        entered.set()
        assert release.wait(5)
        return threading.get_ident()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owned.read, read)
        try:
            assert entered.wait(5)
            owned.close()
            network.get_extra_info.return_value.shutdown.assert_called_once()
            assert not closed_by
        finally:
            release.set()
        reader = future.result(timeout=5)
    assert closed_by == [reader]
    owned.close()
    assert closed_by == [reader]


@pytest.mark.parametrize('started', [False, True])
def test_owned_response_closes_immediately_without_an_active_reader(started):
    stream = Mock()
    owned = io.OwnedResponse(stream)
    if started:
        assert owned.read(lambda: 'chunk') == 'chunk'
    owned.close()
    stream.close.assert_called_once_with()


def test_owned_response_rejects_a_read_while_close_is_running():
    closing, release = threading.Event(), threading.Event()
    read = Mock(return_value='chunk')

    def close():
        closing.set()
        assert release.wait(5)

    owned = io.OwnedResponse(SimpleNamespace(close=close))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owned.close)
        try:
            assert closing.wait(5)
            with pytest.raises(StopIteration):
                owned.read(read)
            read.assert_not_called()
        finally:
            release.set()
        future.result(timeout=5)


def test_owned_response_rejects_a_read_after_deferred_close():
    entered, release = threading.Event(), threading.Event()
    network = Mock()
    response = SimpleNamespace(is_closed=False, http_version='HTTP/1.1',
                               extensions={'network_stream': network})
    close = Mock()
    owned = io.OwnedResponse(SimpleNamespace(response=response, close=close))

    def read():
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owned.read, read)
        try:
            assert entered.wait(5)
            owned.close()
            late_read = Mock()
            with pytest.raises(StopIteration):
                owned.read(late_read)
            late_read.assert_not_called()
            close.assert_not_called()
        finally:
            release.set()
        future.result(timeout=5)
    close.assert_called_once_with()


def test_owned_response_never_reopens_during_deferred_close_cleanup():
    entered, release = threading.Event(), threading.Event()
    transitions = []
    network = Mock()
    response = SimpleNamespace(is_closed=False, http_version='HTTP/1.1',
                               extensions={'network_stream': network})
    close = Mock()
    owned = io.OwnedResponse(SimpleNamespace(response=response, close=close))

    class ObserveLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.saw_pending = False

        def __enter__(self):
            self.lock.acquire()

        def __exit__(self, *exc):
            self.saw_pending |= owned._close_requested
            if self.saw_pending:
                transitions.append((owned._reading, owned._close_requested,
                                    owned._closed))
            self.lock.release()

    owned._lock = ObserveLock()

    def read():
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owned.read, read)
        try:
            assert entered.wait(5)
            owned.close()
        finally:
            release.set()
        future.result(timeout=5)
    assert (False, False, False) not in transitions
    close.assert_called_once_with()


def test_owned_response_closes_http2_reader_without_socket_shutdown():
    entered, release = threading.Event(), threading.Event()
    network = Mock()
    response = SimpleNamespace(is_closed=False, http_version='HTTP/2',
                               extensions={'network_stream': network})
    close = Mock(side_effect=release.set)
    owned = io.OwnedResponse(SimpleNamespace(response=response, close=close))

    def read():
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owned.read, read)
        try:
            assert entered.wait(5)
            owned.close()
        finally:
            release.set()
        future.result(timeout=5)
    owned.close()
    close.assert_called_once_with()
    network.get_extra_info.assert_not_called()


def test_owned_response_remains_exhausted_after_normal_completion():
    class Stream:
        def __init__(self):
            self.iterator = iter(['chunk'])
            self.close = Mock()

        def __iter__(self):
            return self.iterator

    stream = Stream()
    owned = io.OwnedResponse(stream)
    assert next(owned) == 'chunk'
    for _ in range(2):
        with pytest.raises(StopIteration):
            next(owned)
    owned.close()
    stream.close.assert_called_once_with()


def test_dashscope_anthropic_client_accepts_the_custom_transport():
    pytest.importorskip('anthropic')
    from ms_agent.llm.anthropic_llm import Anthropic

    config = OmegaConf.create({'llm': {'model': 'probe'}})
    llm = Anthropic(config, api_key='local-test',
                    base_url='https://dashscope.example.test/compatible-mode/v1')
    try:
        assert llm._is_dashscope
        assert not llm.client.is_closed()
    finally:
        llm.client.close()


class ResponseBody(httpx.SyncByteStream):

    def __init__(self, stream, *, wait_for_body=False, protocol='openai',
                 error_on_close=False):
        self.stream = stream
        self.protocol = protocol
        self.error_on_close = error_on_close
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
        if self.error_on_close and self.closed.is_set():
            raise httpx.ReadError('response interrupted')
        if self.protocol == 'responses':
            response = {
                'id': 'probe', 'object': 'response', 'created_at': 0,
                'model': 'probe', 'status': 'completed',
                'output': [{'id': 'message-probe', 'type': 'message',
                            'role': 'assistant', 'status': 'completed',
                            'content': [{'type': 'output_text', 'text': 'OK',
                                         'annotations': []}]}],
                'usage': {'input_tokens': 1, 'output_tokens': 1,
                          'total_tokens': 2},
            }
            if self.stream:
                for event in [
                    {'type': 'response.output_text.delta', 'delta': 'OK',
                     'item_id': 'message-probe', 'output_index': 0,
                     'content_index': 0, 'sequence_number': 0},
                    {'type': 'response.completed', 'response': response,
                     'sequence_number': 1},
                ]:
                    yield ('data: ' + json.dumps(event) + '\n\n').encode()
            else:
                yield json.dumps(response).encode()
            return
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
               base_url='http://model.test/v1', http_client=None,
               provider_facade=False, responses=False):
    generation = {'stream': stream}
    if responses:
        generation['use_responses_api'] = True
    config = OmegaConf.create({
        'llm': {'model': 'probe'}, 'generation_config': generation})
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
    if responses:
        llm._responses_client = llm.client
    agent = LLMAgent.__new__(LLMAgent)
    agent.llm = (LLMProvider(config, spec=None, transport=llm)
                 if provider_facade else llm)
    agent.config = OmegaConf.create({
        'generation_config': {**generation, 'stream_output': False}})
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
    llm = getattr(agent.llm, 'transport', agent.llm)
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
                       wait_for='headers', error=None, provider_facade=False):
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
                               protocol=protocol, provider_facade=provider_facade)
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


@pytest.mark.parametrize('legacy,provider_facade', [(False, False),
                                                   (True, False),
                                                   (False, True)])
@pytest.mark.parametrize('protocol', ['openai', 'anthropic'])
@pytest.mark.parametrize('stream', [False, True])
@run_async
async def test_cancel_before_headers_closes_late_response_without_reading_body(
        legacy, provider_facade, protocol, stream):
    async with mock_request(protocol, legacy=legacy, stream=stream,
                            provider_facade=provider_facade) as r:
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
async def test_cancel_does_not_close_iterator_until_next_has_unwound(protocol):
    async with mock_request(protocol, wait_for='body') as r:
        release_next = threading.Event()
        iterator_closed = threading.Event()
        premature_close = threading.Event()
        generate = r.agent.llm.generate

        class TrackedIterator:
            def __init__(self, chunks):
                self.chunks = chunks

            def __next__(self):
                try:
                    return next(self.chunks)
                finally:
                    release_next.wait(2)

            def close(self):
                if not release_next.is_set():
                    premature_close.set()
                self.chunks.close()
                iterator_closed.set()

        r.agent.llm.generate = lambda *a, **kw: TrackedIterator(generate(*a, **kw))
        try:
            await reached(r.body.entered)
            await cancel(r.task)
            assert not premature_close.is_set()
            assert not iterator_closed.is_set()
        finally:
            release_next.set()
        await reached(iterator_closed)


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


@pytest.mark.parametrize('protocol,legacy,stream,responses', [
    ('openai', False, True, False), ('anthropic', False, True, False),
    ('openai', True, True, False), ('anthropic', True, True, False),
    ('openai', False, False, False), ('anthropic', False, False, False),
    ('openai', True, False, False), ('anthropic', True, False, False),
    ('openai', True, False, True),
])
@run_async
async def test_cancel_stalled_tcp_read_releases_model_worker(
        monkeypatch, protocol, legacy, stream, responses):
    """A mock close can release an Event while a real socket stays in recv()."""
    release, reading = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
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
            agent = make_agent(legacy=legacy, protocol=protocol, stream=stream,
                               responses=responses,
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


@run_async
async def test_cancel_lazy_responses_headers_closes_late_stream_without_reading(
        monkeypatch):
    entered, release = threading.Event(), threading.Event()
    body = ResponseBody(True, wait_for_body=True, protocol='responses')

    def handle(request):
        entered.set()
        assert release.wait(5)
        return httpx.Response(200, stream=body,
                              headers={'Content-Type': 'text/event-stream'})

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        agent = make_agent(handle, legacy=True, responses=True)
        async with running(agent, release, body.release) as task:
            try:
                await reached(entered)
                await cancel(task)
                release.set()
                await reached(body.closed)
                assert not body.entered.is_set()
                assert await asyncio.wait_for(
                    io.run_in_llm_executor(lambda: 'worker released'), .5) == 'worker released'
                agent.handle_new_response.assert_not_called()
            finally:
                release.set()
                body.release.set()


@run_async
async def test_lazy_responses_stream_normal_completion_preserves_output():
    body = ResponseBody(True, protocol='responses')
    agent = make_agent(
        lambda request: httpx.Response(
            200, stream=body, headers={'Content-Type': 'text/event-stream'}),
        legacy=True, responses=True)
    async with running(agent) as task:
        await asyncio.wait_for(task, 2)
        assert agent.handle_new_response.call_args.args[1].content == 'OK'
        assert body.closed.is_set()


NONSTREAM_ENGINES = [
    ('openai', False, False), ('anthropic', False, False),
    ('openai', True, False), ('anthropic', True, False),
    ('openai', True, True),
]


@pytest.mark.parametrize('protocol,legacy,responses', NONSTREAM_ENGINES)
@run_async
async def test_cancel_nonstream_read_does_not_retry_or_poison_next_request(
        monkeypatch, protocol, legacy, responses):
    body_protocol = 'responses' if responses else protocol
    first = ResponseBody(False, wait_for_body=True, protocol=body_protocol,
                         error_on_close=True)
    second = ResponseBody(False, protocol=body_protocol)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200, stream=first if len(requests) == 1 else second,
            headers={'Content-Type': 'application/json'})

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        agent = make_agent(handle, stream=False, legacy=legacy,
                           protocol=protocol, provider_facade=not legacy,
                           responses=responses)
        engine = getattr(agent.llm, 'transport', agent.llm)
        async with running(agent, first.release, second.release) as task:
            queued = None
            try:
                await reached(first.entered)
                await cancel(task)
                assert first.closed.is_set()
                queued = asyncio.create_task(
                    io.run_in_llm_executor(lambda: 'next request'))
                assert await asyncio.wait_for(
                    asyncio.shield(queued), .5) == 'next request'
                assert len(requests) == 1
                assert getattr(engine, '_request_cancel', None) is None
                result = await asyncio.wait_for(agent._generate_response(
                    [Message(role='user', content='Respond with OK')], []), 2)
                assert result.content == 'OK'
                assert len(requests) == 2
                assert getattr(engine, '_request_cancel', None) is None
            finally:
                first.release.set()
                second.release.set()
                if queued is not None:
                    await asyncio.wait_for(queued, 5)


@pytest.mark.parametrize('protocol,legacy,responses', NONSTREAM_ENGINES)
@run_async
async def test_cancel_during_retry_backoff_releases_worker(monkeypatch, protocol,
                                                         legacy, responses):
    from ms_agent.utils.llm_utils import wait_before_retry

    waiting = threading.Event()
    requests = []
    body = ResponseBody(False, protocol='responses' if responses else protocol)

    def wait(delay, cancelled, owner=None):
        assert cancelled is not None
        assert owner._request_cancel is cancelled
        waiting.set()
        wait_before_retry(delay, cancelled, owner)

    monkeypatch.setattr('ms_agent.utils.llm_utils.wait_before_retry', wait)
    monkeypatch.setattr('ms_agent.llm.retry.wait_before_retry', wait)

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, json={'error': {
                'type': 'server_error', 'message': 'temporary failure'}})
        return httpx.Response(200, stream=body,
                              headers={'Content-Type': 'application/json'})

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        agent = make_agent(handle, stream=False, legacy=legacy,
                           protocol=protocol, provider_facade=not legacy,
                           responses=responses)
        engine = getattr(agent.llm, 'transport', agent.llm)
        async with running(agent, body.release) as task:
            await reached(waiting)
            await cancel(task)
            assert await asyncio.wait_for(
                io.run_in_llm_executor(lambda: 'worker released'), .5) == 'worker released'
            assert len(requests) == 1
            assert getattr(engine, '_request_cancel', None) is None
            result = await asyncio.wait_for(agent._generate_response(
                [Message(role='user', content='Respond with OK')], []), 2)
            assert result.content == 'OK'
            assert len(requests) == 2


@pytest.mark.parametrize('protocol,legacy,responses', NONSTREAM_ENGINES)
@run_async
async def test_transient_retry_preserves_request_cancellation_scope(
        monkeypatch, protocol, legacy, responses):
    requests, events, delays = [], [], []
    body = ResponseBody(False, protocol='responses' if responses else protocol)

    def wait(delay, cancelled, owner=None):
        assert cancelled is not None and not cancelled.is_set()
        assert owner._request_cancel is cancelled
        delays.append(delay)

    monkeypatch.setattr('ms_agent.utils.llm_utils.wait_before_retry', wait)
    monkeypatch.setattr('ms_agent.llm.retry.wait_before_retry', wait)

    def handle(request):
        requests.append(request)
        events.append(engine._request_cancel)
        if len(requests) == 1:
            return httpx.Response(503, json={'error': {
                'type': 'server_error', 'message': 'temporary failure'}})
        return httpx.Response(200, stream=body,
                              headers={'Content-Type': 'application/json'})

    agent = make_agent(handle, stream=False, legacy=legacy, protocol=protocol,
                       provider_facade=not legacy, responses=responses)
    engine = getattr(agent.llm, 'transport', agent.llm)
    try:
        result = await asyncio.wait_for(agent._generate_response(
            [Message(role='user', content='Respond with OK')], []), 2)
        assert result.content == 'OK'
        assert len(requests) == 2
        assert events[0] is events[1] and events[0] is not None
        assert delays == [3.0 if legacy else 1.0]
        assert getattr(engine, '_request_cancel', None) is None
    finally:
        engine.client.close()


def test_cancelled_owned_request_never_calls_resource():
    from ms_agent.utils.llm_utils import request_cancellation

    owner = SimpleNamespace(_active_stream=None)
    resource = SimpleNamespace(create=Mock())
    with request_cancellation(owner) as cancelled:
        cancelled.set()
        with pytest.raises(asyncio.CancelledError):
            io.create_owned_response(resource, owner, model='probe')
        resource.create.assert_not_called()
        assert owner._request_cancel is cancelled
    assert owner._request_cancel is None


def test_request_cancellation_isolated_from_a_previous_context():
    from contextvars import Context
    from ms_agent.utils.llm_utils import request_cancellation

    owner = SimpleNamespace(_request_cancel=None)
    with request_cancellation(owner) as previous:
        previous.set()

        def fresh_call():
            with request_cancellation(owner) as fresh:
                assert fresh is not previous and not fresh.is_set()

        Context().run(fresh_call)
    assert owner._request_cancel is None


def test_finished_request_scope_is_not_reused_from_a_copied_context():
    from contextvars import copy_context
    from ms_agent.utils.llm_utils import request_cancellation

    owner = SimpleNamespace(_request_cancel=None)
    with request_cancellation(owner) as previous:
        previous.set()
        context = copy_context()

    def fresh_call():
        with request_cancellation(owner) as fresh:
            assert fresh is not previous and not fresh.is_set()

    context.run(fresh_call)
    assert owner._request_cancel is None


def test_cancelled_scope_does_not_interrupt_a_replacement_request():
    from ms_agent.utils.llm_utils import raise_if_cancelled

    cancelled, replacement = threading.Event(), threading.Event()
    cancelled.set()
    owner = SimpleNamespace(_request_cancel=replacement, interrupt=Mock())
    with pytest.raises(asyncio.CancelledError):
        raise_if_cancelled(cancelled, owner)
    owner.interrupt.assert_not_called()
    assert not replacement.is_set()


def test_cancelled_late_response_does_not_overwrite_a_replacement():
    from contextlib import contextmanager

    entered, release = threading.Event(), threading.Event()
    owner = SimpleNamespace(_active_stream=None)
    raw = SimpleNamespace(http_response=httpx.Response(200),
                          parse=Mock(), close=Mock())

    @contextmanager
    def create(**kwargs):
        entered.set()
        assert release.wait(5)
        try:
            yield raw
        finally:
            raw.close()

    resource = SimpleNamespace(with_streaming_response=SimpleNamespace(create=create))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(io.create_owned_response, resource, owner)
        try:
            assert entered.wait(5)
            owner._request_cancel.set()
            replacement = SimpleNamespace(close=Mock())
            replacement_cancel = threading.Event()
            owner._request_cancel = replacement_cancel
            owner._active_stream = replacement
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            future.result(timeout=5)
    assert owner._active_stream is replacement
    assert owner._request_cancel is replacement_cancel
    raw.parse.assert_not_called()
    raw.close.assert_called_once_with()
    replacement.close.assert_not_called()


@pytest.mark.parametrize('protocol,legacy,responses', NONSTREAM_ENGINES)
@run_async
async def test_cancel_before_generate_starts_never_sends_request(
        monkeypatch, protocol, legacy, responses):
    entered, release = threading.Event(), threading.Event()
    body = ResponseBody(False, protocol='responses' if responses else protocol)
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=body,
                              headers={'Content-Type': 'application/json'})

    with ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(io, '_executor', pool)
        agent = make_agent(handle, stream=False, legacy=legacy,
                           protocol=protocol, provider_facade=not legacy,
                           responses=responses)
        generate = agent.llm.generate

        def delayed_generate(*args, **kwargs):
            entered.set()
            assert release.wait(5)
            return generate(*args, **kwargs)

        agent.llm.generate = delayed_generate
        async with running(agent, release) as task:
            try:
                await reached(entered)
                await cancel(task)
            finally:
                release.set()
            assert await asyncio.wait_for(
                io.run_in_llm_executor(lambda: 'worker released'), .5) == 'worker released'
            assert not requests
            result = await asyncio.wait_for(agent._generate_response(
                [Message(role='user', content='Respond with OK')], []), 2)
            assert result.content == 'OK' and len(requests) == 1


def test_owned_request_checks_cancellation_after_context_exit():
    from contextlib import contextmanager

    owner = SimpleNamespace(_active_stream=None)
    raw = SimpleNamespace(http_response=httpx.Response(200),
                          parse=Mock(return_value='parsed'), close=Mock())

    @contextmanager
    def create(**kwargs):
        try:
            yield raw
        finally:
            raw.close()
            owner._request_cancel.set()

    resource = SimpleNamespace(with_streaming_response=SimpleNamespace(create=create))
    with pytest.raises(asyncio.CancelledError):
        io.create_owned_response(resource, owner, model='probe')
    raw.parse.assert_called_once_with()
    raw.close.assert_called_once_with()
    assert owner._active_stream is None and owner._request_cancel is None


def test_owned_request_preserves_custom_create_resource():
    owner = SimpleNamespace(_active_stream=None)
    resource = SimpleNamespace(create=Mock(return_value='custom response'))
    assert io.create_owned_response(resource, owner, model='probe') == 'custom response'
    resource.create.assert_called_once_with(model='probe')
    assert owner._active_stream is None and owner._request_cancel is None


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
