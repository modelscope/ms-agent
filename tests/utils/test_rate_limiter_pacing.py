# Copyright (c) ModelScope Contributors. All rights reserved.
"""Concurrent callers must observe the same request-start spacing."""
import asyncio
import time

import pytest
from ms_agent.utils.rate_limiter import RateLimiter


@pytest.mark.parametrize('max_concurrent', [1, 4])
def test_minimum_interval_between_concurrent_requests(max_concurrent):
    async def run():
        limiter = RateLimiter(
            max_requests_per_second=100,
            min_request_interval=0.05,
            max_concurrent=max_concurrent,
        )
        starts = []

        async def request():
            async with limiter:
                starts.append(time.monotonic())

        await asyncio.wait_for(
            asyncio.gather(*(request() for _ in range(4))), timeout=3)
        gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
        assert all(gap >= 0.045 for gap in gaps), gaps

    asyncio.run(run())


def test_spacing_does_not_serialize_request_bodies():
    async def run():
        limiter = RateLimiter(
            max_requests_per_second=100,
            min_request_interval=0.05,
            max_concurrent=3,
        )
        starts = []
        all_entered = asyncio.Event()

        async def request():
            async with limiter:
                starts.append(time.monotonic())
                if len(starts) == 3:
                    all_entered.set()
                await all_entered.wait()

        await asyncio.wait_for(
            asyncio.gather(*(request() for _ in range(3))), timeout=3)
        gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
        assert all(gap >= 0.045 for gap in gaps), gaps

    asyncio.run(run())


def test_requests_per_second_still_limits_concurrent_requests():
    async def run():
        limiter = RateLimiter(
            max_requests_per_second=2,
            min_request_interval=0.05,
            max_concurrent=3,
        )
        starts = []

        async def request():
            async with limiter:
                starts.append(time.monotonic())

        await asyncio.wait_for(
            asyncio.gather(*(request() for _ in range(3))), timeout=3)
        assert starts[1] - starts[0] >= 0.045
        assert starts[2] - starts[0] >= 1.0

    asyncio.run(run())
