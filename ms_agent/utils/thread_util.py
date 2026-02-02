# Copyright (c) Alibaba, Inc. and its affiliates.
import os
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

from ms_agent.utils.logger import get_logger
from tqdm.auto import tqdm

logger = get_logger()

DEFAULT_MAX_WORKERS = int(
    os.getenv('DEFAULT_MAX_WORKERS', min(8,
                                         os.cpu_count() + 4)))


def thread_executor(max_workers: int = DEFAULT_MAX_WORKERS,
                    disable_tqdm: bool = False,
                    tqdm_desc: str = None):
    """
    A decorator to execute a function in a threaded manner using ThreadPoolExecutor.

    Args:
        max_workers (int): The maximum number of threads to use.
        disable_tqdm (bool): disable progress bar.
        tqdm_desc (str): Desc of tqdm.

    Returns:
        function: A wrapped function that executes with threading and a progress bar.

    Examples:
        >>> from modelscope.utils.thread_utils import thread_executor
        >>> import time
        >>> @thread_executor(max_workers=8)
        ... def process_item(item, x, y):
        ...     # do something to single item
        ...     time.sleep(1)
        ...     return str(item) + str(x) + str(y)

        >>> items = [1, 2, 3]
        >>> process_item(items, x='abc', y='xyz')
    """

    def decorator(func):

        @wraps(func)
        def wrapper(iterable, *args, **kwargs):
            results = []
            # Create a tqdm progress bar with the total number of items to process
            with tqdm(
                    unit_scale=True,
                    unit_divisor=1024,
                    initial=0,
                    total=len(iterable),
                    desc=tqdm_desc or f'Processing {len(iterable)} items',
                    disable=disable_tqdm,
            ) as pbar:
                # Define a wrapper function to update the progress bar
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all tasks
                    futures = {
                        executor.submit(func, item, *args, **kwargs): item
                        for item in iterable
                    }

                    # Update the progress bar as tasks complete
                    for future in as_completed(futures):
                        pbar.update(1)
                        results.append(future.result())
            return results

        return wrapper

    return decorator


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """
    A ThreadPoolExecutor whose worker threads are daemon threads.

    Why:
    - In this repo, we run synchronous network calls in `run_in_executor`.
    - When the outer coroutine times out/cancels, the underlying thread keeps running.
    - Non-daemon worker threads then block process shutdown (Python waits for them).

    Using daemon threads ensures a finished CLI process can exit cleanly even if
    some background executor work is still blocked in I/O.
    """

    def _adjust_thread_count(self) -> None:  # pragma: no cover
        # Based on CPython ThreadPoolExecutor._adjust_thread_count, but mark
        # threads as daemon before starting.
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = '%s_%d' % (self._thread_name_prefix
                                     or self, num_threads)
            # Import internal helpers from stdlib to keep behavior consistent.
            from concurrent.futures.thread import _worker, _threads_queues  # type: ignore

            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(weakref.ref(self, weakref_cb), self._work_queue,
                      self._initializer, self._initargs),
            )
            t.daemon = True
            t.start()
            self._threads.add(t)
            _threads_queues[t] = self._work_queue
