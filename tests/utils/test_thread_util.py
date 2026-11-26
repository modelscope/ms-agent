import threading

from ms_agent.utils.thread_util import DaemonThreadPoolExecutor


def test_daemon_executor_initializes_workers_and_reuses_them():
    local = threading.local()

    def initialize(value):
        local.value = value

    def work():
        return local.value, threading.current_thread()

    with DaemonThreadPoolExecutor(
            max_workers=1, initializer=initialize, initargs=('ready',)) as pool:
        value, first = pool.submit(work).result(timeout=5)
        assert value == 'ready'
        assert first.daemon
        assert pool.submit(work).result(timeout=5)[1] is first
    assert not first.is_alive()


def test_daemon_executor_shutdown_cancels_pending_work():
    entered, release = threading.Event(), threading.Event()
    pool = DaemonThreadPoolExecutor(max_workers=1)

    def wait():
        entered.set()
        assert release.wait(5)
        return 'finished'

    try:
        running = pool.submit(wait)
        assert entered.wait(5)
        pending = pool.submit(lambda: 'should not run')
        pool.shutdown(wait=False, cancel_futures=True)
        assert pending.cancelled()
        release.set()
        assert running.result(timeout=5) == 'finished'
    finally:
        release.set()
        pool.shutdown(wait=True)
