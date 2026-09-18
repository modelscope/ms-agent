# Copyright (c) ModelScope Contributors. All rights reserved.
"""Keep blocking model I/O out of the application's default executor."""
import asyncio
import contextvars
import socket
from concurrent.futures import ThreadPoolExecutor

# Shared, bounded, and started lazily by ThreadPoolExecutor. Its lifetime is
# the process's; the executor joins its workers on process exit. Slow models
# must not occupy the host's executor for session storage and cancellation.
_executor = ThreadPoolExecutor(thread_name_prefix='ms-agent-llm')


async def run_in_llm_executor(func, *args):
    context = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(
        _executor, context.run, func, *args)


def interrupt_stream(stream):
    """Interrupt an owned HTTP/1 response before closing its SDK stream.

    A socket close in another thread need not wake a blocked recv(). Shutdown
    does. Never shut down an HTTP/2 connection, which may carry other requests.
    Custom transports without HTTPX's network extension retain normal close.
    """
    try:
        response = getattr(stream, 'response', None)
        if (response is not None and not response.is_closed
                and response.http_version in ('HTTP/1.0', 'HTTP/1.1')):
            network = response.extensions.get('network_stream')
            sock = network.get_extra_info('socket') if network else None
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
    except Exception:  # shutdown is best effort; always attempt SDK cleanup
        pass
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
