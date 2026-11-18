# Copyright (c) Alibaba, Inc. and its affiliates.
"""Offline lifecycle tests for rate-limiter concurrency slots."""
import asyncio
import unittest
from unittest.mock import patch

from ms_agent.utils.rate_limiter import RateLimiter


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):

    async def _assert_entry_succeeds(self, limiter):

        async def enter():
            async with limiter as entered:
                self.assertIs(entered, limiter)
                self.assertTrue(limiter._semaphore.locked())

        try:
            await asyncio.wait_for(enter(), timeout=1)
        except asyncio.TimeoutError:
            self.fail('A subsequent request could not acquire the slot')

    async def test_cancel_during_pacing_releases_slot(self):
        limiter = RateLimiter(
            max_requests_per_second=100,
            min_request_interval=60,
            max_concurrent=1)
        async with limiter:
            pass

        sleeping = asyncio.Event()
        original_sleep = asyncio.sleep

        async def observed_sleep(delay):
            sleeping.set()
            await original_sleep(delay)

        async def enter():
            async with limiter:
                self.fail('The cancelled request must not enter the body')

        with patch('ms_agent.utils.rate_limiter.asyncio.sleep',
                   observed_sleep):
            task = asyncio.create_task(enter())
            try:
                await asyncio.wait_for(sleeping.wait(), timeout=1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        limiter.min_request_interval = 0
        await self._assert_entry_succeeds(limiter)

    async def test_pacing_error_releases_slot(self):
        limiter = RateLimiter(min_request_interval=0, max_concurrent=1)
        error = RuntimeError('pacing failed')
        with patch.object(limiter, '_wait_if_needed', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                async with limiter:
                    self.fail('Failed entry must not execute the body')
        self.assertIs(caught.exception, error)

        await self._assert_entry_succeeds(limiter)

    async def test_cancel_before_acquiring_does_not_release_another_slot(self):
        limiter = RateLimiter(min_request_interval=0, max_concurrent=1)
        started = asyncio.Event()

        async def enter():
            started.set()
            async with limiter:
                self.fail('The cancelled request must not enter the body')

        async with limiter:
            task = asyncio.create_task(enter())
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertTrue(limiter._semaphore.locked())

        await self._assert_entry_succeeds(limiter)

    async def test_normal_exit_releases_slot(self):
        limiter = RateLimiter(min_request_interval=0, max_concurrent=1)
        for _ in range(2):
            await self._assert_entry_succeeds(limiter)
            self.assertFalse(limiter._semaphore.locked())

    async def test_body_error_releases_slot_and_propagates(self):
        limiter = RateLimiter(min_request_interval=0, max_concurrent=1)
        error = RuntimeError('body failed')
        with self.assertRaises(RuntimeError) as caught:
            async with limiter:
                raise error
        self.assertIs(caught.exception, error)
        await self._assert_entry_succeeds(limiter)
