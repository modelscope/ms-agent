# Copyright (c) ModelScope Contributors. All rights reserved.
import asyncio
import functools
import re
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Event
from typing import (Any, AsyncGenerator, Callable, Optional, Tuple, Type,
                    TypeVar, Union)

from .logger import get_logger

logger = get_logger()

T = TypeVar('T')
_request_scope = ContextVar('llm_request_cancellation', default=None)

# 4xx statuses that CAN succeed on a resend: request timeout, lock conflict,
# too-early, and rate limiting. Every other 4xx is a verdict on the request
# itself — resending the identical payload just buys the same rejection.
_RETRYABLE_CLIENT_STATUSES = frozenset({408, 409, 425, 429})

# Providers surface the status inconsistently: the openai/anthropic SDKs expose
# `status_code`, while gateways often only put it in the message
# ("APIError: <400> ...", "Error code: 400 - {...}").
_STATUS_IN_TEXT = re.compile(r'<(\d{3})>|(?:error\s+)?code[:=]?\s*(\d{3})\b',
                             re.IGNORECASE)


def http_status_of(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP status for a provider exception, or None if unknown."""
    for attr in ('status_code', 'http_status', 'status'):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    match = _STATUS_IN_TEXT.search(str(exc))
    if match:
        status = int(match.group(1) or match.group(2))
        if 100 <= status <= 599:
            return status
    return None


def is_retryable_error(exc: BaseException) -> bool:
    """Whether resending the same request could plausibly succeed.

    Unknown/None status keeps the historical behaviour (retry), so transient
    network faults are unaffected. Only an identifiable, non-transient 4xx
    fails fast — previously a hard 400 (bad payload, content filter, missing
    field) burned all five attempts plus 15s of backoff before surfacing.
    """
    status = http_status_of(exc)
    if status is None:
        return True
    if 400 <= status < 500:
        return status in _RETRYABLE_CLIENT_STATUSES
    return True


@dataclass
class _RequestScope:
    owner: Any
    cancelled: Event
    bind_owner: bool = True
    active: bool = True


@contextmanager
def request_cancellation(owner, cancelled=None, *, bind_owner=True):
    current = _request_scope.get()
    # Copied contexts can outlive the request that created them.
    same_request = (current is not None and current.active
                    and current.owner is owner
                    and (cancelled is None or cancelled is current.cancelled))
    if same_request:
        if not bind_owner or current.bind_owner:
            yield current.cancelled
            return
        cancelled = current.cancelled
    if cancelled is None:
        cancelled = Event()
    scope = _RequestScope(owner, cancelled, bind_owner=bind_owner)
    token = _request_scope.set(scope)
    if bind_owner:
        owner._request_cancel = cancelled
    try:
        yield cancelled
    finally:
        scope.active = False
        if bind_owner and getattr(owner, '_request_cancel', None) is cancelled:
            owner._request_cancel = None
        _request_scope.reset(token)


def raise_if_cancelled(cancelled: Optional[Event], owner=None):
    if cancelled is not None and cancelled.is_set():
        if (owner is not None
                and getattr(owner, '_request_cancel', None) is cancelled):
            try:
                owner.interrupt()
            except Exception:
                pass
        raise asyncio.CancelledError()


def wait_before_retry(delay: float, cancelled: Optional[Event], owner=None):
    if cancelled is None:
        time.sleep(delay)
    else:
        cancelled.wait(delay)
        raise_if_cancelled(cancelled, owner)


def retry(max_attempts: int = 3,
          delay: float = 1.0,
          backoff_factor: float = 2.0,
          exceptions: Union[Type[Exception], Tuple[Type[Exception],
                                                   ...]] = Exception,
          cancellation_owner: Optional[Callable] = None):
    """Retry doing something"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            owner = cancellation_owner(args[0]) if cancellation_owner else None
            scope = (request_cancellation(owner)
                     if owner is not None else nullcontext())
            with scope as cancelled:
                current_delay = delay
                last_exception = None
                for attempt in range(1, max_attempts + 1):
                    raise_if_cancelled(cancelled, owner)
                    try:
                        result = func(*args, **kwargs)
                        raise_if_cancelled(cancelled, owner)
                        return result
                    except exceptions as e:
                        raise_if_cancelled(cancelled, owner)
                        import traceback
                        logger.warning(traceback.format_exc())
                        last_exception = e
                        if attempt < max_attempts:
                            logger.warning(
                                f'Attempt {attempt}/{max_attempts} fails: {func.__name__}. '
                                f'Exception message: {e}. Will retry in {current_delay:.2f} seconds.'
                            )
                            wait_before_retry(current_delay, cancelled, owner)
                            current_delay *= backoff_factor
                        else:
                            logger.error(
                                f'Attempt to call {func.__name__} over {max_attempts} times. '
                                f'The last exception message: {e}')
                raise last_exception

        return wrapper

    return decorator


def async_retry(max_attempts: int = 3,
                delay: float = 1.0,
                backoff_factor: float = 2.0,
                exceptions: Union[Type[Exception], Tuple[Type[Exception],
                                                         ...]] = Exception,
                retry_if: Optional[Callable[[BaseException], bool]] = None):
    """Retry doing something.

    ``retry_if`` short-circuits the loop for exceptions that cannot succeed on
    a resend (see :func:`is_retryable_error`); the exception is still raised,
    just without burning the remaining attempts and their backoff.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> AsyncGenerator[T, Any]:
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                    return
                except exceptions as e:
                    import traceback
                    logger.warning(traceback.format_exc())
                    last_exception = e
                    if retry_if is not None and not retry_if(e):
                        logger.error(
                            f'{func.__name__} failed unrecoverably on attempt '
                            f'{attempt}/{max_attempts}; not retrying. '
                            f'Exception message: {e}')
                        break
                    if attempt < max_attempts:
                        logger.warning(
                            f'Attempt {attempt}/{max_attempts} fails: {func.__name__}. '
                            f'Exception message: {e}. Will retry in {current_delay:.2f} seconds.'
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(
                            f'Attempt to call {func.__name__} over {max_attempts} times. '
                            f'The last exception message: {e}')
            raise last_exception

        return wrapper

    return decorator
