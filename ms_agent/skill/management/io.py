"""Cancellation-safe ownership of short filesystem work."""
import asyncio


async def complete_io(function, *args):
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A second cancellation (for example cancel followed by shutdown)
        # must not detach a thread that still owns a filesystem transaction.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            # Consume a failure while preserving cancellation.
            task.exception()
        raise
