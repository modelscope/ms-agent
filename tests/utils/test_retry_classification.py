"""async_retry's ``retry_if`` gate: don't burn attempts on unrecoverable 4xx.

A hard 400 (bad payload, missing field, content filter) is a verdict on the
request — resending the identical body five times only adds ~15s of backoff
before the same failure surfaces. Transient faults must keep retrying.
"""
import asyncio

import pytest
from ms_agent.utils import async_retry, is_retryable_error
from ms_agent.utils.llm_utils import http_status_of


class _ApiError(Exception):
    """Stand-in for a provider SDK error, with or without ``status_code``."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


@pytest.mark.parametrize(
    'exc, expected',
    [
        # Real strings observed in production, where the status is only in text.
        (_ApiError('APIError: <400> InternalError.Algo.DataInspectionFailed: '
                   'Output data may contain inappropriate content.'), 400),
        (_ApiError("Error code: 400 - {'error': {'message': 'missing field "
                   "`tool_call_id`'}}"), 400),
        # Structured SDK errors.
        (_ApiError('boom', 429), 429),
        (_ApiError('boom', 503), 503),
        # Nothing status-like.
        (ConnectionError('Connection reset by peer'), None),
    ],
)
def test_http_status_extraction(exc, expected):
    assert http_status_of(exc) == expected


@pytest.mark.parametrize('status', [400, 401, 403, 404, 422])
def test_client_errors_are_not_retryable(status):
    assert is_retryable_error(_ApiError('boom', status)) is False


@pytest.mark.parametrize('status', [408, 409, 425, 429, 500, 502, 503])
def test_transient_and_server_errors_stay_retryable(status):
    assert is_retryable_error(_ApiError('boom', status)) is True


@pytest.mark.parametrize(
    'exc',
    [ConnectionError('reset'),
     TimeoutError('timed out'),
     Exception('something odd')])
def test_unknown_errors_keep_retrying(exc):
    # Conservative default: an unidentifiable failure behaves as before.
    assert is_retryable_error(exc) is True


def _run(fn):
    async def drive():
        async for _ in fn():
            pass

    with pytest.raises(Exception):
        asyncio.run(drive())


def test_unrecoverable_error_uses_exactly_one_attempt():
    calls = []

    @async_retry(max_attempts=5, delay=10.0, retry_if=is_retryable_error)
    async def boom():
        calls.append(1)
        raise _ApiError('APIError: <400> DataInspectionFailed')
        yield  # pragma: no cover - makes this an async generator

    _run(boom)
    # delay=10.0 would make a retrying implementation take >=10s; one attempt
    # also proves no backoff was slept.
    assert len(calls) == 1


def test_transient_error_still_exhausts_attempts():
    calls = []

    @async_retry(max_attempts=3, delay=0.01, retry_if=is_retryable_error)
    async def flaky():
        calls.append(1)
        raise ConnectionError('reset')
        yield  # pragma: no cover

    _run(flaky)
    assert len(calls) == 3


def test_without_retry_if_behaviour_is_unchanged():
    calls = []

    @async_retry(max_attempts=3, delay=0.01)
    async def boom():
        calls.append(1)
        raise _ApiError('APIError: <400> DataInspectionFailed')
        yield  # pragma: no cover

    _run(boom)
    assert len(calls) == 3
