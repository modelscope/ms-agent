# Copyright (c) Alibaba, Inc. and its affiliates.
"""Offline tests for synchronous and asynchronous rate-limited calls."""
import asyncio
import functools
import threading
import unittest

from ms_agent.utils.rate_limiter import RateLimiter


class TestRateLimiterExecute(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.limiter = RateLimiter(
            max_requests_per_second=100,
            min_request_interval=0,
            max_concurrent=1)

    async def test_sync_positional_and_keyword_arguments(self):
        caller_thread = threading.get_ident()

        def combine(left, *, right):
            self.assertNotEqual(threading.get_ident(), caller_thread)
            return left + right

        self.assertEqual(await self.limiter.execute(combine, 2, right=3), 5)

    async def test_sync_keyword_only_arguments(self):

        def fetch_data(*, url):
            return url

        self.assertEqual(
            await self.limiter.execute(fetch_data, url='offline-value'),
            'offline-value')

    async def test_sync_executor_named_keywords_reach_callable(self):

        def receive(**kwargs):
            return kwargs

        self.assertEqual(
            await self.limiter.execute(receive, executor='target-value'),
            {'executor': 'target-value'})

    async def test_sync_positional_arguments_still_work(self):
        self.assertEqual(await self.limiter.execute(pow, 2, 3), 8)

    async def test_sync_no_arguments_still_work(self):
        self.assertEqual(await self.limiter.execute(lambda: 'result'), 'result')

    async def test_sync_partial_preserves_bound_and_call_time_arguments(self):

        def combine(first, second, *, suffix):
            return first + second + suffix

        operation = functools.partial(combine, 'first-')
        self.assertEqual(
            await self.limiter.execute(operation, 'second-', suffix='end'),
            'first-second-end')

    async def test_sync_exception_is_propagated_and_slot_is_released(self):
        error = ValueError('function failed')

        def fail(*, reason):
            self.assertEqual(reason, 'expected')
            raise error

        with self.assertRaises(ValueError) as caught:
            await self.limiter.execute(fail, reason='expected')
        self.assertIs(caught.exception, error)
        result = await asyncio.wait_for(
            self.limiter.execute(lambda: 'next'), timeout=1)
        self.assertEqual(result, 'next')

    async def test_async_keyword_arguments_stay_on_event_loop(self):
        caller_thread = threading.get_ident()

        async def combine(left, *, right):
            self.assertEqual(threading.get_ident(), caller_thread)
            await asyncio.sleep(0)
            return left + right

        self.assertEqual(await self.limiter.execute(combine, 2, right=3), 5)

    async def test_async_exception_is_propagated(self):
        error = ValueError('async function failed')

        async def fail(*, reason):
            self.assertEqual(reason, 'expected')
            raise error

        with self.assertRaises(ValueError) as caught:
            await self.limiter.execute(fail, reason='expected')
        self.assertIs(caught.exception, error)
