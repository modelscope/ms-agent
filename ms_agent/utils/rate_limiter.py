# Copyright (c) Alibaba, Inc. and its affiliates.
import asyncio
import time
from collections import deque
from typing import Callable

from ms_agent.utils import get_logger

logger = get_logger()


class RateLimiter:
    """
    Supports the following rate limiting strategies:
    1. Maximum requests per second
    2. Minimum request interval
    3. Maximum concurrency
    Thread-safe, supports async operations.

    Args:
        max_requests_per_second: Maximum requests per second, default 2
        min_request_interval: Minimum request interval (seconds), default 0.5
        max_concurrent: Maximum concurrency, default 3

    Example:
        >>> limiter = RateLimiter(max_requests_per_second=2, min_request_interval=0.5)
        >>> async def fetch_data():
        ...     async with limiter:
        ...         result = await api_call()
        ...     return result
    """

    def __init__(
        self,
        max_requests_per_second: int = 2,
        min_request_interval: float = 0.5,
        max_concurrent: int = 3,
    ):
        self.max_requests_per_second = max_requests_per_second
        self.min_request_interval = min_request_interval
        self.max_concurrent = max_concurrent

        # Request time records (using deque for performance)
        self._request_times = deque(maxlen=max_requests_per_second)
        self._last_request_time = 0.0

        # Concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()

        logger.info(
            f'RateLimiter initialized: {max_requests_per_second} req/s, '
            f'min_interval={min_request_interval}s, max_concurrent={max_concurrent}'
        )

    async def __aenter__(self):
        """Async context manager entry"""
        await self._semaphore.acquire()
        await self._wait_if_needed()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        self._semaphore.release()
        return False

    async def _wait_if_needed(self):
        """Check and wait to satisfy rate limits"""
        now = time.time()

        # 1. Check minimum request interval
        if self._last_request_time > 0:
            elapsed = now - self._last_request_time
            if elapsed < self.min_request_interval:
                wait_time = self.min_request_interval - elapsed
                logger.debug(
                    f'Enforcing min interval: waiting {wait_time:.3f}s')
                await asyncio.sleep(wait_time)
                now = time.time()

        # 2. Check requests per second limit
        async with self._lock:
            # Clean up expired request records (older than 1 second)
            cutoff_time = now - 1.0
            while self._request_times and self._request_times[0] < cutoff_time:
                self._request_times.popleft()

            # If rate limit reached, wait until oldest request expires
            if len(self._request_times) >= self.max_requests_per_second:
                oldest_request = self._request_times[0]
                wait_time = 1.0 - (now
                                   - oldest_request) + 0.01  # Add 10ms margin
                if wait_time > 0:
                    logger.debug(
                        f'Rate limit reached ({self.max_requests_per_second} req/s): '
                        f'waiting {wait_time:.3f}s')
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    # Clean up expired records
                    cutoff_time = now - 1.0
                    while self._request_times and self._request_times[
                            0] < cutoff_time:
                        self._request_times.popleft()

            # Record this request time
            self._request_times.append(now)
            self._last_request_time = now

    async def execute(self, func: Callable, *args, **kwargs):
        """
        Execute function call with rate limiting

        Args:
            func: Function to execute (can be sync or async)
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function return value

        Example:
            >>> limiter = RateLimiter()
            >>> result = await limiter.execute(fetch_data, url='https://example.com')
        """
        async with self:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                # Execute sync function in thread pool
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, func, *args, **kwargs)

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics

        Returns:
            Dictionary containing current state
        """
        with self._lock:
            now = time.time()
            cutoff_time = now - 1.0
            recent_requests = sum(1 for t in self._request_times
                                  if t >= cutoff_time)

            return {
                'max_requests_per_second':
                self.max_requests_per_second,
                'min_request_interval':
                self.min_request_interval,
                'max_concurrent':
                self.max_concurrent,
                'recent_requests_count':
                recent_requests,
                'available_concurrent_slots':
                self._semaphore._value,
                'last_request_ago':
                now - self._last_request_time
                if self._last_request_time > 0 else None,
            }

    def reset(self):
        """Reset rate limiter state"""
        with self._lock:
            self._request_times.clear()
            self._last_request_time = 0.0
            logger.info('RateLimiter reset')


class AdaptiveRateLimiter(RateLimiter):
    """
    Dynamically adjusts rate limits based on request success rate and error types.
    Automatically reduces request rate when rate limit errors are detected;
    Gradually recovers rate when requests are consistently successful.

    Args:
        initial_requests_per_second: Initial requests per second
        min_requests_per_second: Minimum requests per second
        max_requests_per_second: Maximum requests per second
        backoff_factor: Backoff factor during rate limiting (default 0.5, i.e., halve)
        recovery_factor: Recovery growth factor (default 1.2)
        error_threshold: Consecutive errors threshold to trigger rate reduction
        success_threshold: Consecutive successes threshold to trigger recovery
    """

    def __init__(
        self,
        initial_requests_per_second: int = 2,
        min_requests_per_second: int = 1,
        max_requests_per_second: int = 10,
        min_request_interval: float = 0.5,
        max_concurrent: int = 3,
        backoff_factor: float = 0.5,
        recovery_factor: float = 1.2,
        error_threshold: int = 3,
        success_threshold: int = 10,
    ):
        super().__init__(
            max_requests_per_second=initial_requests_per_second,
            min_request_interval=min_request_interval,
            max_concurrent=max_concurrent,
        )

        self._min_rps = min_requests_per_second
        self._max_rps = max_requests_per_second
        self._backoff_factor = backoff_factor
        self._recovery_factor = recovery_factor
        self._error_threshold = error_threshold
        self._success_threshold = success_threshold

        self._consecutive_errors = 0
        self._consecutive_successes = 0
        self._total_requests = 0
        self._total_errors = 0

        logger.info(
            f'AdaptiveRateLimiter initialized: {initial_requests_per_second} req/s '
            f'(range: {min_requests_per_second}-{max_requests_per_second})')

    def record_success(self):
        """Record successful request"""
        with self._lock:
            self._total_requests += 1
            self._consecutive_successes += 1
            self._consecutive_errors = 0

            # Consecutive successes reached threshold, attempt to increase rate
            if self._consecutive_successes >= self._success_threshold:
                old_rps = self.max_requests_per_second
                new_rps = min(
                    round(old_rps * self._recovery_factor), self._max_rps)
                if new_rps > old_rps:
                    self.max_requests_per_second = new_rps
                    logger.info(
                        f'Rate limit increased: {old_rps} → {new_rps} req/s '
                        f'(after {self._consecutive_successes} successes)')
                self._consecutive_successes = 0

    def record_error(self, is_rate_limit_error: bool = False):
        """
        Record failed request

        Args:
            is_rate_limit_error: Whether this is a rate limit error
        """
        with self._lock:
            self._total_requests += 1
            self._total_errors += 1
            self._consecutive_errors += 1
            self._consecutive_successes = 0

            # If rate limit error, immediately reduce rate
            if is_rate_limit_error:
                old_rps = self.max_requests_per_second
                new_rps = max(
                    int(old_rps * self._backoff_factor), self._min_rps)
                if new_rps < old_rps:
                    self.max_requests_per_second = new_rps
                    # Also increase minimum request interval
                    self.min_request_interval = min(
                        self.min_request_interval * 1.5, 2.0)
                    logger.warning(
                        f'Rate limit error detected! Reducing rate: {old_rps} → {new_rps} req/s, '
                        f'min_interval → {self.min_request_interval:.2f}s')
                self._consecutive_errors = 0

            # Consecutive errors reached threshold, reduce rate
            elif self._consecutive_errors >= self._error_threshold:
                old_rps = self.max_requests_per_second
                new_rps = max(
                    int(old_rps * self._backoff_factor), self._min_rps)
                if new_rps < old_rps:
                    self.max_requests_per_second = new_rps
                    logger.warning(
                        f'Multiple errors detected! Reducing rate: {old_rps} → {new_rps} req/s '
                        f'(after {self._consecutive_errors} errors)')
                self._consecutive_errors = 0

    def get_stats(self) -> dict:
        """Get extended statistics"""
        stats = super().get_stats()
        with self._lock:
            stats.update({
                'total_requests':
                self._total_requests,
                'total_errors':
                self._total_errors,
                'error_rate':
                self._total_errors / max(self._total_requests, 1),
                'consecutive_successes':
                self._consecutive_successes,
                'consecutive_errors':
                self._consecutive_errors,
                'current_requests_per_second':
                self.max_requests_per_second,
            })
        return stats
