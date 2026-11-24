# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keep blocking model I/O out of the application's default executor."""
import asyncio
import contextvars
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

# Shared, bounded, and started lazily by ThreadPoolExecutor. Its lifetime is
# the process's; the executor joins its workers on process exit. Slow models
# must not occupy the host's executor for session storage and cancellation.
_executor = ThreadPoolExecutor(thread_name_prefix='ms-agent-llm')


async def run_in_llm_executor(func, *args):
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        _executor, context.run, func, *args)


def _shutdown_socket(stream):
    try:
        response = getattr(stream, 'response', None)
        if (response is not None and not response.is_closed
                and response.http_version in ('HTTP/1.0', 'HTTP/1.1')):
            network = response.extensions.get('network_stream')
            sock = network.get_extra_info('socket') if network else None
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
                return True
    except Exception:
        pass
    return False


class OwnedResponse:
    """Keep cross-thread interruption separate from a reader's final close."""

    def __init__(self, stream):
        self._stream = stream
        self._iterator = None
        self._lock = threading.Lock()
        self._reading = False
        self._close_requested = False
        self._closed = False

    @property
    def response(self):
        return getattr(self._stream, 'response', None)

    def read(self, function, *args):
        with self._lock:
            if self._closed or self._close_requested:
                raise StopIteration
            self._reading = True
        try:
            return function(*args)
        finally:
            with self._lock:
                self._reading = False
                close_requested = self._close_requested
                if close_requested:
                    self._closed = True
                    self._close_requested = False
            if close_requested:
                self._close_stream()

    def __iter__(self):
        return self

    def __next__(self):
        if self._iterator is None:
            self._iterator = iter(self._stream)
        try:
            return self.read(next, self._iterator)
        except BaseException:
            self.close()
            raise

    def close(self):
        with self._lock:
            if self._closed or self._close_requested:
                return
            if self._reading and _shutdown_socket(self):
                # Closing here can race a timed recv() on Darwin even after shutdown.
                self._close_requested = True
                return
            self._closed = True
        self._close_stream()

    def _close_stream(self):
        try:
            self._stream.close()
        except Exception:
            pass


def interrupt_stream(stream):
    if not isinstance(stream, OwnedResponse):
        _shutdown_socket(stream)
    try:
        if stream is not None:
            stream.close()
    except Exception:
        pass


class OpenedStream:
    """Open a lazy stream manager while the request still owns cancellation.

    Anthropic sends the HTTP request in __enter__, not messages.stream().
    Opening it during generate() lets LLMAgent close a late response before
    reading any body. The consumer retains the manager's context protocol.
    """

    def __init__(self, manager):
        self._manager = manager
        self._stream = manager.__enter__()

    def __enter__(self):
        return self._stream

    @property
    def response(self):
        return getattr(self._stream, 'response', None)

    def __exit__(self, *exc):
        return self._manager.__exit__(*exc)

    def close(self):
        self.__exit__(None, None, None)


def create_owned_stream(resource, owner, **kwargs):
    from ms_agent.utils.llm_utils import (raise_if_cancelled,
                                          request_cancellation)

    with request_cancellation(owner) as cancelled:
        stream = None
        try:
            raise_if_cancelled(cancelled)
            stream = OwnedResponse(resource.create(**kwargs))
            raise_if_cancelled(cancelled)
            owner._active_stream = stream
            raise_if_cancelled(cancelled)
            return stream
        except BaseException:
            interrupt_stream(stream)
            if getattr(owner, '_active_stream', None) is stream:
                owner._active_stream = None
            raise_if_cancelled(cancelled)
            raise


def create_owned_response(resource, owner, **kwargs):
    """Expose response ownership before synchronous JSON parsing blocks on body I/O.

    Both SDKs provide with_streaming_response without changing the wire's
    stream=false request. Custom resources can keep their ordinary create API.
    """
    import inspect
    from types import SimpleNamespace
    from ms_agent.utils.llm_utils import (raise_if_cancelled,
                                          request_cancellation)

    with request_cancellation(owner) as cancelled:
        active = None
        try:
            raise_if_cancelled(cancelled)
            if inspect.getattr_static(resource, 'with_streaming_response',
                                      None) is None:
                result = resource.create(**kwargs)
            else:
                with resource.with_streaming_response.create(**kwargs) as raw:
                    raise_if_cancelled(cancelled)
                    active = OwnedResponse(SimpleNamespace(
                        response=raw.http_response, close=raw.close))
                    owner._active_stream = active
                    raise_if_cancelled(cancelled)
                    result = active.read(raw.parse)
            raise_if_cancelled(cancelled)
            return result
        except Exception:
            raise_if_cancelled(cancelled)
            raise
        finally:
            if getattr(owner, '_active_stream', None) is active:
                owner._active_stream = None
