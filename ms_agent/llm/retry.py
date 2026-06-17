# Copyright (c) ModelScope Contributors. All rights reserved.
"""Error classification and adaptive retry for LLM calls.

Unlike a blind ``@retry``, this distinguishes transient failures (429/5xx/
timeout/overloaded -> worth retrying with backoff) from terminal ones
(auth/quota/bad-request -> fail fast). Honors ``Retry-After`` when present.
"""
from __future__ import annotations

import functools
import time
from enum import Enum
from typing import Callable

from ms_agent.utils import get_logger

logger = get_logger()


class ErrorCategory(str, Enum):
    TRANSIENT = 'transient'  # 429 / 5xx / timeout / overloaded -> retry
    QUOTA = 'quota'          # insufficient balance/quota -> fail fast
    AUTH = 'auth'            # 401 / 403 -> fail fast
    CLIENT = 'client'        # 400 / 422 -> fail fast
    UNKNOWN = 'unknown'      # anything else -> retry (bounded)


def classify_error(error: Exception) -> ErrorCategory:
    error_str = str(error).lower()
    status_code = getattr(error, 'status_code', None)

    if status_code == 429 or 'rate limit' in error_str or 'too many requests' \
            in error_str:
        return ErrorCategory.TRANSIENT
    if status_code in (500, 502, 503, 504):
        return ErrorCategory.TRANSIENT
    if 'timeout' in error_str or 'timed out' in error_str:
        return ErrorCategory.TRANSIENT
    if 'overloaded' in error_str:
        return ErrorCategory.TRANSIENT
    if status_code in (401, 403) or 'unauthorized' in error_str \
            or 'invalid api key' in error_str:
        return ErrorCategory.AUTH
    if 'insufficient' in error_str and ('quota' in error_str
                                        or 'balance' in error_str):
        return ErrorCategory.QUOTA
    if status_code in (400, 422):
        return ErrorCategory.CLIENT
    return ErrorCategory.UNKNOWN


_NON_RETRYABLE = (ErrorCategory.AUTH, ErrorCategory.QUOTA, ErrorCategory.CLIENT)


def smart_retry(max_attempts: int = 3,
                base_delay: float = 1.0,
                max_delay: float = 30.0):
    """Retry decorator that respects error category and backoff."""

    def decorator(func: Callable):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001 - re-raised below
                    last_error = e
                    category = classify_error(e)
                    if category in _NON_RETRYABLE:
                        logger.warning(
                            f'Non-retryable error ({category.value}): {e}')
                        raise
                    if attempt < max_attempts - 1:
                        delay = min(base_delay * (2**attempt), max_delay)
                        retry_after = getattr(e, 'retry_after', None)
                        if retry_after:
                            try:
                                delay = max(delay, float(retry_after))
                            except (TypeError, ValueError):
                                pass
                        logger.info(
                            f'Retrying in {delay:.1f}s '
                            f'(attempt {attempt + 1}/{max_attempts}, '
                            f'category={category.value}): {e}')
                        time.sleep(delay)
                    else:
                        logger.error(
                            f'All {max_attempts} attempts failed: {e}')
            raise last_error

        return wrapper

    return decorator
