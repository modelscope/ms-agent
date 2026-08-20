# Copyright (c) ModelScope Contributors. All rights reserved.
"""Retry a request whose rejection arrives *after* the HTTP response starts.

``llm/thinking.py`` and ``llm/vision.py`` both repair a request the endpoint
refuses (drop the thinking parameters / drop the image blocks) and try once
more. Both used to guard only the ``create(...)`` call, on the assumption
spelled out in their docstrings: "the client performs the request — and raises —
before it returns an iterator".

That holds for the OpenAI Python SDK, which does issue the HTTP request eagerly.
It does **not** hold for gateways that answer 200 and then put the error in the
stream. Measured on an Aliyun-family endpoint::

    APIError: <400> InternalError.Algo.InvalidParameter: The thinking_budget
    parameter must be a positive integer and not greater than 0

arrives while the first chunk is being read, i.e. *outside* the ``try`` — so
neither fallback saw it, nothing was retried, nothing was remembered, and the
raw provider error reached the user.

The window this module reopens is deliberately narrow: only the FIRST advance of
the stream is guarded. Until then nothing has been handed to the caller, so
replacing the stream wholesale is invisible and safe. Once a single chunk has
been delivered the turn is already partly rendered, and silently restarting it
would duplicate or contradict what the user has seen — so a later failure is
re-raised untouched.
"""
from __future__ import annotations

from typing import Any, Callable, Iterator


def retry_on_first_chunk(result: Any, repair: Callable[[BaseException],
                                                       Any]) -> Any:
    """Guard the first advance of ``result`` with ``repair``.

    ``result`` is whatever the provider client returned. Non-iterators (a
    non-streaming response object, Anthropic's stream *manager*) are handed back
    untouched — there is no first chunk to guard, and their errors already
    surface eagerly.

    ``repair(exc)`` is the same callable the eager path uses: it either returns
    a replacement result or re-raises. Its replacement is streamed in full, so
    the caller cannot tell which attempt produced the data.
    """
    if not hasattr(result, '__next__'):
        return result

    def _guarded() -> Iterator[Any]:
        source = result
        try:
            first = next(source)
        except StopIteration:
            return
        except Exception as exc:  # noqa: BLE001 — handed to the same repair
            replacement = repair(exc)
            if replacement is not None:
                yield from replacement
            return
        # Past this point the caller has seen output; a failure now is real.
        yield first
        yield from source

    return _guarded()
