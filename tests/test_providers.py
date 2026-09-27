import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image
from nemo_microservices import AsyncNeMoMicroservices
from insurelens.providers import Nvidia, Drugs
from insurelens.core import AppError

ENV = {'NVIDIA_API_KEY': 'test-only-placeholder'}


def completion(content='{}', reason='stop', **message):
    return {'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'test',
            'choices': [{'index': 0, 'finish_reason': reason, 'message': {'role': 'assistant', 'content': content, **message}}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('base', ['https://inference.example/v1', 'https://inference.example/v1/', 'https://inference.example'])
async def test_real_sdk_route_authorization_and_generation(base):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion('{"terms":["독감"]}'))
    provider = Nvidia(env={**ENV, 'NIM_BASE_URL': base, 'NEMO_MICROSERVICES_BASE_URL': 'https://platform.example'}, transport=httpx.MockTransport(handler))
    try:
        assert await provider.chat([{'role': 'user', 'content': '독감'}]) == '{"terms":["독감"]}'
        assert isinstance(provider._sdk, AsyncNeMoMicroservices)
        request = requests[0]
        assert str(request.url) == 'https://inference.example/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer test-only-placeholder'
        body = json.loads(request.content)
        assert body['temperature'] == 0 and body['stream'] is False
        assert body['response_format'] == {'type': 'json_object'}
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        assert body['messages'] == [{'role': 'user', 'content': '독감'}]
        assert len(requests) == 1  # No platform/guardrails requests.
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_sdk_tool_call_envelope_and_payload():
    tools = [{'type': 'function', 'function': {'name': 'search', 'parameters': {'type': 'object', 'properties': {'ids': {'type': 'array', 'items': {'type': 'integer'}}}}}}]
    calls = [{'id': 'call_1', 'type': 'function', 'function': {'name': 'search', 'arguments': '{"ids":[0]}'}}]
    def handler(request):
        body = json.loads(request.content)
        assert body['tools'] == tools and body['tool_choice'] == 'auto'
        assert body['max_tokens'] == 1500
        return httpx.Response(200, json=completion(None, 'tool_calls', tool_calls=calls))
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        result = await provider.complete([{'role': 'user', 'content': '독감'}], tools)
        assert result['finish_reason'] == 'tool_calls'
        assert result['message']['tool_calls'] == calls
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('body', 'error'), [(completion('{}', 'length'), 'NIM_INCOMPLETE_RESPONSE'), (completion('oops'), 'NIM_INVALID_JSON'), (completion(''), 'NIM_INVALID_RESPONSE'), ({'choices': []}, 'NIM_INVALID_RESPONSE')])
async def test_chat_rejects_unusable_responses(body, error):
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    try:
        with pytest.raises(AppError, match=error):
            await provider.chat([])
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'error'), [(401, 'NIM_AUTH_FAILED'), (403, 'NIM_AUTH_FAILED'), (404, 'NIM_MODEL_UNAVAILABLE'), (429, 'NIM_RATE_LIMIT'), (500, 'NIM_SERVICE_UNAVAILABLE')])
async def test_provider_status_errors_do_not_leak_body(status, error):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, json={'secret': 'do not expose'})
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError, match=error) as exc:
            await provider.chat([])
        assert 'secret' not in str(exc.value) and count == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_cancel_propagates_and_missing_key_makes_no_request():
    started = asyncio.Event()
    async def handler(request):
        started.set()
        await asyncio.sleep(60)
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        task = asyncio.create_task(provider.chat([]))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await provider.close()
    provider = Nvidia(env={})
    with pytest.raises(AppError, match='NVIDIA_KEY_REQUIRED'):
        await provider.chat([])
    assert provider._sdk is None
    await provider.close()


@pytest.mark.asyncio
async def test_translation_original_immutable_and_invalid_ids_rejected():
    response = {'glosses': [{'id': 0, 'english': 'influenza'}]}
    provider = Nvidia(env={**ENV, 'TRANSLATION_MODEL': 'translation-model'}, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=completion(json.dumps(response)))))
    terms = ['독감']
    try:
        assert await provider.gloss(terms) == [{'id': 0, 'original': '독감', 'english': 'influenza'}]
        assert terms == ['독감']
        response['glosses'][0]['id'] = 1
        with pytest.raises(AppError, match='TRANSLATION_BOUNDARY'):
            await provider.gloss(terms)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_ocr_reencodes_strips_metadata_and_marks_unconfirmed():
    source = Image.new('RGB', (20, 10), 'white')
    exif = Image.Exif(); exif[270] = 'private metadata'
    data = io.BytesIO(); source.save(data, 'JPEG', exif=exif)
    def handler(request):
        assert str(request.url) == 'https://ocr.example/infer'
        body = json.loads(request.content)
        image = Image.open(io.BytesIO(base64.b64decode(body['input'][0]['url'].split(',')[1])))
        assert image.format == 'PNG' and not image.getexif()
        assert 'exif' not in image.info and 'icc_profile' not in image.info
        return httpx.Response(200, json={'data': [{'text_detections': [{'text_prediction': {'text': '조플루자'}}]}]})
    provider = Nvidia(env={**ENV, 'NIM_OCR_URL': 'https://ocr.example/infer'}, transport=httpx.MockTransport(handler))
    try:
        result = await provider.ocr(data.getvalue(), 'image/jpeg')
        assert result['text'] == '조플루자' and result['requiresConfirmation'] is True
        with pytest.raises(AppError, match='INVALID_IMAGE'):
            await provider.ocr(b'not an image', 'image/png')
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_mfds_maps_only_explicit_official_fields():
    def handler(request):
        assert request.url.params['item_name'] == '조플루자'
        assert request.url.params['serviceKey'] == 'test-mfds'
        return httpx.Response(200, json={'response': {'header': {'resultCode': '00'}, 'body': {'items': {'item': {'ITEM_SEQ': '202012345', 'ITEM_NAME': '조플루자', 'ITEM_INGR_NAME': '발록사비르', 'ENTP_NAME': '제조사', 'ITEM_PERMIT_DATE': '20200101'}}}}})
    provider = Drugs(env={'MFDS_API_KEY': 'test-mfds'}, transport=httpx.MockTransport(handler))
    try:
        result = await provider.lookup('조플루자')
        assert result['requiresSelection'] is True
        products = result['products']
        assert len(products) == 1 and products[0]['ingredients'] == '발록사비르'
        assert products[0]['url'].endswith('itemSeq=202012345')
        assert products[0]['cancelDate'] is None
        assert set(products[0]) == {'id', 'name', 'ingredients', 'manufacturer', 'permitDate', 'cancelDate', 'url', 'retrievedAt'}
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(('failure', 'code'), [(httpx.ReadTimeout, 'NIM_TIMEOUT'), (httpx.ConnectError, 'NIM_UNAVAILABLE')])
async def test_sdk_transport_failure_codes(failure, code):
    def handler(request):
        raise failure('not exposed', request=request)
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError, match=code):
            await provider.chat([])
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_sdk_redirect_does_not_forward_credentials():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={'location': 'https://other.example/steal'})
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError, match='NIM_REQUEST_FAILED'):
            await provider.chat([])
        assert len(requests) == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_input_uses_explicit_schema_and_preserves_source_validation():
    from insurelens.agents.input import understand_input_with_model, TERMS_SCHEMA
    bodies = []
    response = {'terms': ['조플루자']}
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion(json.dumps(response, ensure_ascii=False)))
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        request = {'description': '조플루자를 처방받았어요', 'cloudConsent': True}
        result = await understand_input_with_model(request, provider)
        assert result['terms'] == ['조플루자']
        assert result['description'] == request['description']
        assert bodies[0]['response_format'] == {'type': 'json_schema', 'json_schema': {'name': 'structured_response', 'strict': True, 'schema': TERMS_SCHEMA}}
        assert bodies[0]['chat_template_kwargs']['enable_thinking'] is False
        # Even a provider ignoring the schema cannot invent a diagnosis.
        response['terms'] = ['독감']
        with pytest.raises(AppError, match='UNGROUNDED_TERM'):
            await understand_input_with_model(request, provider)
        response['terms'] = ['조플루자']
        response['extra'] = 'unexpected'
        with pytest.raises(AppError):
            await understand_input_with_model(request, provider)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_input_deadline_cancels_sdk_without_retry_or_local_search(monkeypatch):
    from insurelens.agents import input as input_agent
    assert input_agent.INPUT_TIMEOUT_SECONDS == 60
    monkeypatch.setattr(input_agent, 'INPUT_TIMEOUT_SECONDS', .02)
    cancelled = asyncio.Event()
    count = 0
    async def handler(request):
        nonlocal count
        count += 1
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    provider = Nvidia(env=ENV, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AppError, match='NIM_TIMEOUT'):
            await input_agent.understand_input_with_model({'query': '조플루자', 'cloudConsent': True}, provider)
        assert count == 1 and cancelled.is_set()
    finally:
        await provider.close()
