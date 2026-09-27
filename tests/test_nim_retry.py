import asyncio
import json
from io import StringIO

import httpx
import pytest

from insurelens.core import AppError
from insurelens.diagnostics import RuntimeLog, log_context
from insurelens.providers import Nvidia
from tests.test_providers import completion


@pytest.mark.asyncio
async def test_five_minute_deadline_is_forwarded_and_transient_failure_retries_once(monkeypatch):
    monkeypatch.setattr(Nvidia,'RETRY_DELAY_SECONDS',0)
    requests=[]
    def handle(request):
        requests.append(request)
        assert request.extensions['timeout']['read']==300
        if len(requests)==1:raise httpx.ReadTimeout('private body and key must not escape',request=request)
        return httpx.Response(200,json=completion('{"terms":[]}'))
    provider=Nvidia(env={'NVIDIA_API_KEY':'test-only'},transport=httpx.MockTransport(handle))
    stream=StringIO();logger=RuntimeLog(stream=stream)
    try:
        with log_context(logger):
            result=await provider.chat([{'role':'user','content':'private-test-input'}])
        assert result=='{"terms":[]}' and len(requests)==2
        assert requests[0].content==requests[1].content
        rows=[json.loads(line) for line in stream.getvalue().splitlines()]
        assert [r['attempt'] for r in rows if r['event']=='operation.started']==[1,2]
        retry=[r for r in rows if r['event']=='provider.retry']
        assert len(retry)==1 and retry[0]['code']=='NIM_TIMEOUT' and retry[0]['max_attempts']==2
        assert 'private-test-input' not in stream.getvalue() and 'private body' not in stream.getvalue()
    finally:await provider.close();logger.close()


@pytest.mark.asyncio
async def test_exhausted_retries_make_exactly_two_http_requests(monkeypatch):
    monkeypatch.setattr(Nvidia,'RETRY_DELAY_SECONDS',0)
    count=0
    def handle(request):
        nonlocal count
        count+=1
        return httpx.Response(503,json={'message':'private response'})
    provider=Nvidia(env={'NVIDIA_API_KEY':'test-only'},transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(AppError,match='NIM_SERVICE_UNAVAILABLE'):await provider.chat([])
        assert count==2  # SDK retries must not multiply application attempts.
    finally:await provider.close()


@pytest.mark.asyncio
async def test_each_attempt_has_its_own_deadline_and_sse_continues(monkeypatch):
    from insurelens.progress import model_progress
    monkeypatch.setattr(Nvidia,'RETRY_DELAY_SECONDS',0)
    count=0;cancelled=asyncio.Event();events=[]
    async def handle(request):
        nonlocal count
        count+=1
        if count==1:
            try:await asyncio.Event().wait()
            finally:cancelled.set()
        return httpx.Response(200,json=completion('{}'))
    provider=Nvidia(env={'NVIDIA_API_KEY':'test-only'},transport=httpx.MockTransport(handle))
    try:
        value=await model_progress(provider.chat([],timeout=.02),emit=lambda event,data:events.append((event,data)),stage='input',label='검색 1단계',interval=.003)
        assert value=='{}' and count==2 and cancelled.is_set()
        assert any(e=='stage_progress' for e,_ in events) and events[-1][0]=='stage_completed'
    finally:await provider.close()


@pytest.mark.asyncio
async def test_cancelling_backoff_prevents_second_request(monkeypatch):
    import insurelens.providers as module
    monkeypatch.setattr(Nvidia,'RETRY_DELAY_SECONDS',30)
    retry=asyncio.Event();count=0
    def record(event,**kwargs):
        if event=='provider.retry':retry.set()
    monkeypatch.setattr(module,'record',record)
    def handle(request):
        nonlocal count
        count+=1
        raise httpx.ReadTimeout('redacted',request=request)
    provider=Nvidia(env={'NVIDIA_API_KEY':'test-only'},transport=httpx.MockTransport(handle))
    try:
        task=asyncio.create_task(provider.chat([]))
        await asyncio.wait_for(retry.wait(),2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert count==1
    finally:await provider.close()


@pytest.mark.asyncio
async def test_tool_call_is_returned_once_after_retry_without_replaying_tools(monkeypatch):
    monkeypatch.setattr(Nvidia,'RETRY_DELAY_SECONDS',0)
    calls=0
    tool=[{'id':'retry-tool','type':'function','function':{'name':'search_policy','arguments':'{"ids":[0]}'}}]
    def handle(request):
        nonlocal calls
        calls+=1
        if calls==1:raise httpx.ConnectError('redacted',request=request)
        return httpx.Response(200,json=completion(None,'tool_calls',tool_calls=tool))
    provider=Nvidia(env={'NVIDIA_API_KEY':'test-only'},transport=httpx.MockTransport(handle))
    try:
        result=await provider.complete([],[])
        assert calls==2 and result['message']['tool_calls']==tool
    finally:await provider.close()
