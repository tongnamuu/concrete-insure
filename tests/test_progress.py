import asyncio
import pytest
from concreteinsure.progress import model_progress
from concreteinsure.core import AppError


@pytest.mark.asyncio
async def test_pending_provider_reports_elapsed_then_complete_without_content():
    release = asyncio.Event()
    heartbeat = asyncio.Event()
    events = []
    async def operation():
        await release.wait()
        return {'private': 'never emit this'}
    def emit(event, data):
        events.append((event, data))
        if event == 'stage_progress':
            heartbeat.set()
    task = asyncio.create_task(model_progress(operation(), emit=emit, stage='input', label='입력 확인', interval=.01))
    await asyncio.wait_for(heartbeat.wait(), 1)
    assert not task.done()
    release.set()
    assert await task == {'private': 'never emit this'}
    assert events[0][0] == 'stage_started' and events[-1][0] == 'stage_completed'
    assert any(event == 'stage_progress' and data['elapsedSeconds'] >= 0 for event, data in events)
    assert 'private' not in str(events)
    previous = len(events)
    await asyncio.sleep(.03)
    assert len(events) == previous


@pytest.mark.asyncio
async def test_cancelling_progress_also_cancels_provider():
    started, cancelled = asyncio.Event(), asyncio.Event()
    events = []
    async def operation():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    task = asyncio.create_task(model_progress(operation(), emit=lambda *e: events.append(e), stage='input', label='입력 확인', interval=.01))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert not any(event == 'stage_completed' for event, _ in events)


@pytest.mark.asyncio
async def test_progress_propagates_provider_failure_without_retry():
    calls = 0
    events = []
    async def operation():
        nonlocal calls
        calls += 1
        raise AppError('NIM_TIMEOUT', 504)
    with pytest.raises(AppError, match='NIM_TIMEOUT'):
        await model_progress(operation(), emit=lambda *e: events.append(e), stage='planning', label='검색 단계 확인')
    assert calls == 1 and [event for event, _ in events] == ['stage_started']
