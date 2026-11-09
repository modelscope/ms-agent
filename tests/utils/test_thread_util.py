# Copyright (c) ModelScope Contributors. All rights reserved.
"""Daemon workers must not turn non-waiting shutdown into an exit-time join."""
import subprocess
import sys
import textwrap
import threading

import pytest
from ms_agent.utils.thread_util import DaemonThreadPoolExecutor


def test_nonwaiting_shutdown_does_not_block_process_exit():
    script = textwrap.dedent('''
        import threading
        from ms_agent.utils.thread_util import DaemonThreadPoolExecutor

        started = threading.Event()
        blocked = threading.Event()

        def work():
            started.set()
            blocked.wait()

        executor = DaemonThreadPoolExecutor(max_workers=1)
        executor.submit(work)
        assert started.wait(5)
        executor.shutdown(wait=False, cancel_futures=True)
        print('shutdown returned', flush=True)
    ''')
    result = subprocess.run(
        [sys.executable, '-c', script], capture_output=True, text=True,
        timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'shutdown returned' in result.stdout


def test_results_and_exceptions_are_preserved():
    with DaemonThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(lambda: 42).result(timeout=5) == 42
        future = executor.submit(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            future.result(timeout=5)


def test_waiting_shutdown_joins_workers():
    executor = DaemonThreadPoolExecutor(max_workers=1)
    future = executor.submit(lambda: threading.current_thread())
    worker = future.result(timeout=5)
    assert worker.daemon
    executor.shutdown(wait=True)
    assert not worker.is_alive()


def test_nonwaiting_shutdown_cancels_queued_work():
    started = threading.Event()
    release = threading.Event()

    def work():
        started.set()
        release.wait(5)

    executor = DaemonThreadPoolExecutor(max_workers=1)
    running = executor.submit(work)
    try:
        assert started.wait(5)
        queued = executor.submit(lambda: 'should not run')
        executor.shutdown(wait=False, cancel_futures=True)
        assert queued.cancelled()
    finally:
        release.set()
        running.result(timeout=5)
        executor.shutdown(wait=True)
