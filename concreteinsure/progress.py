"""Report provider waits without exposing model text or changing execution."""
import asyncio
import time


async def model_progress(operation, *, emit, stage, label, interval=5):
    started = time.monotonic()
    emit('stage_started', {'stage': stage, 'message': label})
    task = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            elapsed = round(time.monotonic() - started, 1)
            if done:
                result = await task
                emit('stage_completed', {'stage': stage, 'elapsedSeconds': elapsed,
                                        'message': label})
                return result
            emit('stage_progress', {'stage': stage, 'elapsedSeconds': elapsed,
                                   'message': label})
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
