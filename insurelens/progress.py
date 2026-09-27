"""Report provider waits without exposing model text or changing execution."""
import asyncio
import time


async def model_progress(operation, *, emit, stage, label, interval=5):
    started = time.monotonic()
    emit('stage_started', {'stage': stage, 'message': f'NVIDIA에서 {label} 중입니다.'})
    task = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            elapsed = round(time.monotonic() - started, 1)
            if done:
                result = await task
                emit('stage_completed', {'stage': stage, 'elapsedSeconds': elapsed,
                                        'message': f'NVIDIA {label} 응답을 받았습니다.'})
                return result
            emit('stage_progress', {'stage': stage, 'elapsedSeconds': elapsed,
                                   'message': f'NVIDIA 응답을 기다리고 있습니다. ({label} · {int(elapsed)}초 경과)'})
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
