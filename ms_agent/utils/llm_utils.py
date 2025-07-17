# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import functools
import time
from typing import Callable, Tuple, Type, TypeVar, Union

from .logger import get_logger

logger = get_logger()

T = TypeVar('T')


def retry(max_attempts: int = 3,
          delay: float = 1.0,
          backoff_factor: float = 2.0,
          exceptions: Union[Type[Exception], Tuple[Type[Exception],
                                                   ...]] = Exception):
    """Retry doing something"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        logger.warning(
                            f'Attempt {attempt}/{max_attempts} fails: {func.__name__}. '
                            f'Exception message: {e}. Will retry in {current_delay:.2f} seconds.'
                        )
                        time.sleep(current_delay)
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
                                                         ...]] = Exception):
    """Retry doing something"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                    return
                except exceptions as e:
                    last_exception = e
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
