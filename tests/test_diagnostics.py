import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from insurelens.core import AppError
from insurelens.diagnostics import RuntimeLog, log_context, measured, record
from insurelens.providers import Nvidia
from insurelens.server import create_app
from insurelens.store import Queue, Store

SECRET = 'private-prescription-and-nvapi-secret'


def rows(folder):
    return [json.loads(line) for file in sorted(Path(folder).glob('*.jsonl*')) for line in file.read_text().splitlines()]


def test_logs_rotate_are_private_and_drop_unapproved_values(tmp_path):
    log = RuntimeLog(tmp_path / 'logs', max_bytes=800, backups=2)
    for _ in range(30):
        with log_context(log, request_id=str(uuid4())):
            record('provider.response', category='nim', prompt_tokens=12, completion_tokens=3,
                   total_tokens=10**500, route='/'+SECRET, model=SECRET, finish_reason=SECRET,
                   messages=SECRET, headers={'Authorization': SECRET}, query=SECRET,
                   response=SECRET, filename=SECRET, code='bad\n'+SECRET)
    log.close()
    files = list((tmp_path / 'logs').iterdir())
    assert 1 < len(files) <= 3
    assert all(file.stat().st_mode & 0o777 == 0o600 for file in files)
    assert (tmp_path / 'logs').stat().st_mode & 0o777 == 0o700
    for value in rows(tmp_path / 'logs'):
        assert SECRET not in json.dumps(value)
        assert value['model'] == 'custom' and value['route'] == 'unmatched'
        assert value['prompt_tokens'] == 12 and 'total_tokens' not in value
        assert 'request_id' in value and value['timestamp'].endswith('+00:00')


async def test_queue_correlates_success_failure_and_cancelled_before_start(tmp_path):
    log = RuntimeLog(tmp_path / 'logs')
    store = Store(tmp_path / 'store')
    queue = Queue(store)
    case = store.create('private-owner')
    request_ids = [str(uuid4()) for _ in range(3)]
    jobs = [store.create_job(case['id'], 'investigation') for _ in range(3)]
    async def success(emit):
        emit('stage_started', {'stage': 'input', 'message': SECRET, 'query': SECRET})
        async with measured('nim', 'chat'):
            await asyncio.sleep(.02)
        emit('stage_completed', {'stage': 'input', 'elapsedSeconds': .02, 'response': SECRET})
        return {'never_log': SECRET}
    async def fail(emit):
        raise RuntimeError(SECRET)
    tasks = []
    try:
        for request_id, job, fn in zip(request_ids, jobs, [success, fail, success]):
            with log_context(log, request_id=request_id):
                tasks.append(queue.add(job, fn))
        queue.cancel(jobs[2])
        await asyncio.gather(*tasks, return_exceptions=True)
        values = rows(tmp_path / 'logs')
        assert SECRET not in json.dumps(values)
        assert {v['job_id'] for v in values} == set(jobs)
        for request_id, job, state in zip(request_ids, jobs, ['completed', 'failed', 'cancelled']):
            related = [v for v in values if v['job_id'] == job]
            assert {v['request_id'] for v in related} == {request_id}
            finished = [v for v in related if v['event'] == 'job.finished']
            assert len(finished) == 1 and finished[0]['state'] == state
            assert finished[0]['duration_ms'] >= 0
        assert store.job(jobs[1], 'private-owner')['error'] == 'PROCESSING_FAILED'
        assert not any(v['event'] == 'job.started' and v['job_id'] == jobs[2] for v in values)
        assert any(v['event'] == 'job.stage' and v['stage'] == 'input' for v in values)
    finally:
        await queue.close()
        store.close()
        log.close()


@pytest.mark.parametrize('status', [200, 401])
async def test_real_sdk_logs_only_timings_usage_and_error_codes(tmp_path, status):
    def handler(request):
        if status != 200:
            return httpx.Response(status, json={'error': SECRET})
        return httpx.Response(200, json={'id': SECRET, 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{"private":"'+SECRET+'"}'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    provider = Nvidia(env={'NVIDIA_API_KEY': SECRET}, transport=httpx.MockTransport(handler))
    log = RuntimeLog(tmp_path / 'logs')
    try:
        with log_context(log, request_id=str(uuid4()), job_id=str(uuid4())):
            if status == 200:
                await provider.chat([{'role': 'user', 'content': SECRET}])
            else:
                with pytest.raises(AppError, match='NIM_AUTH_FAILED'):
                    await provider.chat([{'role': 'user', 'content': SECRET}])
        values = rows(tmp_path / 'logs')
        assert SECRET not in json.dumps(values)
        assert values[0]['event'] == 'operation.started'
        assert values[-1]['duration_ms'] >= 0
        if status == 200:
            response = next(v for v in values if v['event'] == 'provider.response')
            assert response['finish_reason'] == 'stop' and response['total_tokens'] == 15
            assert values[-1]['event'] == 'operation.completed'
        else:
            assert values[-1]['event'] == 'operation.failed' and values[-1]['code'] == 'NIM_AUTH_FAILED'
    finally:
        await provider.close()
        log.close()


async def test_cancellation_is_logged_and_context_does_not_leak(tmp_path):
    log = RuntimeLog(tmp_path / 'logs')
    started = asyncio.Event()
    async def run():
        async with measured('nim', 'chat'):
            started.set()
            await asyncio.Event().wait()
    with log_context(log, request_id=str(uuid4())):
        task = asyncio.create_task(run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    before = log.path.read_text()
    record('app.started')  # Restored outside the scope: no process-global logger.
    assert log.path.read_text() == before
    assert rows(tmp_path / 'logs')[-1]['event'] == 'operation.cancelled'
    log.close()


async def test_http_job_correlation_no_bodies_cookies_or_raw_paths(tmp_path):
    async def investigate(emit, **kwargs):
        emit('stage_progress', {'stage': 'input', 'elapsedSeconds': 5, 'message': SECRET})
        async with measured('nim', 'chat'):
            await asyncio.sleep(.01)
        return {'quotes': [], 'mode': 'nim-react'}
    app = create_app(root=tmp_path, nim=SimpleNamespace(enabled=True, translation_model=''),
                     drugs=SimpleNamespace(enabled=False), investigate=investigate)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
        base_url='http://localhost', headers={'X-Local-Request': '1', 'X-Request-ID': SECRET}) as client:
        case = (await client.post('/api/cases')).json()['id']
        app.state.store.set_document(case, {'id': str(uuid4()), 'pdf': SECRET, 'index': SECRET})
        response = await client.post(f'/api/cases/{case}/investigations', json={'query': SECRET, 'cloudConsent': True})
        assert response.status_code == 202
        request_id = response.headers['X-Request-ID']
        assert request_id != SECRET
        job_id = response.json()['jobId']
        async with asyncio.timeout(5):
            while app.state.store.job(job_id, client.cookies['insurelens_session'])['state'] != 'completed':
                await asyncio.sleep(.01)
        bad = await client.get('/api/jobs/'+SECRET, params={'private': SECRET})
        assert bad.status_code == 400
        denied = await client.post('/api/cases', headers={'Origin': 'https://'+SECRET})
        assert denied.status_code == 403 and denied.headers['X-Request-ID']
        values = rows(tmp_path / 'logs')
        assert SECRET not in json.dumps(values)
        job_rows = [v for v in values if v.get('job_id') == job_id]
        assert job_rows and all(v['request_id'] == request_id for v in job_rows)
        http_row = next(v for v in values if v['event'] == 'request.completed' and v['request_id'] == request_id)
        assert http_row['status'] == 202 and http_row['route'] == '/api/cases/{identifier}/investigations'
        assert any(v['event'] == 'job.stage' and v['elapsed_seconds'] == 5 for v in job_rows)
    assert rows(tmp_path / 'logs')[-1]['event'] == 'app.stopped'


def test_restart_records_interrupted_job_without_user_data(tmp_path):
    store = Store(tmp_path / 'data')
    case = store.create(SECRET)
    job = store.create_job(case['id'], 'investigation')
    store.close()
    log = RuntimeLog(tmp_path / 'logs')
    with log_context(log):
        store = Store(tmp_path / 'data')
    assert len(rows(tmp_path / 'logs')) == 1
    value = rows(tmp_path / 'logs')[0]
    assert value['event'] == 'job.finished' and value['job_id'] == job and value['code'] == 'SERVER_RESTARTED'
    assert SECRET not in json.dumps(value)
    store.close()
    log.close()


async def test_nim_timeout_is_recorded_with_elapsed_time(tmp_path):
    async def handler(request):
        await asyncio.Event().wait()
    provider = Nvidia(env={'NVIDIA_API_KEY': SECRET}, transport=httpx.MockTransport(handler))
    log = RuntimeLog(tmp_path / 'logs')
    try:
        with log_context(log, request_id=str(uuid4())):
            with pytest.raises(AppError, match='NIM_TIMEOUT'):
                await provider.chat([{'role': 'user', 'content': SECRET}], timeout=.02)
        value = rows(tmp_path / 'logs')[-1]
        assert value['event'] == 'operation.failed' and value['code'] == 'NIM_TIMEOUT'
        assert value['duration_ms'] >= 10 and value['timeout_seconds'] == .02
        assert SECRET not in json.dumps(rows(tmp_path / 'logs'))
    finally:
        await provider.close()
        log.close()
