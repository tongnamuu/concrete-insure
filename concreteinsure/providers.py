"""Official NeMo Microservices SDK inference and explicit external evidence tools.

SDK 1.5.0 exposes chat.completions.create on the root client; inference_base_url
routes that resource independently from optional NeMo platform services.
"""
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from nemo_microservices import AsyncNeMoMicroservices, APIStatusError, APITimeoutError, APIConnectionError

from .core import AppError, ensure
from .diagnostics import measured, record

LIMIT = 4_000_000


def _nim_error(status):
    code = {401: 'NIM_AUTH_FAILED', 403: 'NIM_AUTH_FAILED', 404: 'NIM_MODEL_UNAVAILABLE',
            410: 'NIM_MODEL_UNAVAILABLE', 429: 'NIM_RATE_LIMIT'}.get(status)
    return AppError(code or ('NIM_SERVICE_UNAVAILABLE' if status >= 500 else 'NIM_REQUEST_FAILED'),
                    429 if status == 429 else 502)


async def _json_request(client, method, url, service='MFDS', **kwargs):
    async with measured('mfds', 'http'):
        return await _send_json_request(client, method, url, service=service, **kwargs)


async def _send_json_request(client, method, url, service='MFDS', **kwargs):
    try:
        async with client.stream(method, url, **kwargs) as response:
            record('provider.response', category='mfds', status=response.status_code)
            if not 200 <= response.status_code < 300:
                raise AppError('PROVIDER_REQUEST_FAILED', 502)
            parts = bytearray()
            async for part in response.aiter_bytes():
                parts.extend(part)
                ensure(len(parts) < LIMIT, 'PROVIDER_RESPONSE_LIMIT', 502)
        try:
            return json.loads(parts)
        except (ValueError, UnicodeError):
            raise AppError('PROVIDER_INVALID_JSON', 502) from None
    except httpx.TimeoutException:
        raise AppError(service + '_TIMEOUT', 504) from None
    except httpx.HTTPError:
        raise AppError(service + '_UNAVAILABLE', 502) from None


class Nvidia:
    TIMEOUT_SECONDS = 300
    RETRY_DELAY_SECONDS = 1
    MAX_ATTEMPTS = 2
    RETRYABLE_ERRORS = {'NIM_TIMEOUT', 'NIM_UNAVAILABLE', 'NIM_SERVICE_UNAVAILABLE'}

    def __init__(self, env=os.environ, client=None, transport=None):
        self.key = env.get('NVIDIA_API_KEY', '')
        self.base = env.get('NIM_BASE_URL') or 'https://integrate.api.nvidia.com/v1'
        self.model = env.get('NIM_MODEL') or 'nvidia/nemotron-3.5-lightning-30b-a3b'
        self.microservices_base = env.get('NEMO_MICROSERVICES_BASE_URL', '')
        self._sdk = client
        self._transport = transport

    @property
    def enabled(self):
        return bool(self.key)

    def _client(self):
        if self._sdk is None:
            # SDK appends /v1/chat/completions itself. Preserve any proxy prefix.
            inference = re.sub(r'/v1$', '', self.base.rstrip('/'))
            self._sdk = AsyncNeMoMicroservices(
                base_url=self.microservices_base or inference,
                inference_base_url=inference,
                default_headers={'Authorization': f'Bearer {self.key}'},
                timeout=self.TIMEOUT_SECONDS, max_retries=0,  # Retries are bounded by _completion below.
                http_client=httpx.AsyncClient(transport=self._transport, timeout=self.TIMEOUT_SECONDS, follow_redirects=False),
            )
        return self._sdk

    @staticmethod
    def generation_options(model):
        return {'chat_template_kwargs': {'enable_thinking': False}} if re.match(r'^nvidia/nemotron-(?:3(?:[.-]|$)|nano-3)', model) else {}

    async def _completion(self, messages, model, *, tools=None, response_schema=None, timeout=TIMEOUT_SECONDS):
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                async with measured('nim', 'tools' if tools is not None else 'chat', model=model,
                                    timeout_seconds=timeout, attempt=attempt, max_attempts=self.MAX_ATTEMPTS,
                                    response_mode='tools' if tools is not None else ('schema' if response_schema is not None else 'json')):
                    return await self._send_completion(messages, model, tools=tools, response_schema=response_schema, timeout=timeout)
            except AppError as error:
                if attempt == self.MAX_ATTEMPTS or error.code not in self.RETRYABLE_ERRORS:
                    raise
                record('provider.retry', category='nim', code=error.code, attempt=attempt + 1,
                       max_attempts=self.MAX_ATTEMPTS, delay_seconds=self.RETRY_DELAY_SECONDS)
                # No tools have been executed for a failed completion. Retry only
                # that immutable inference request, never the whole investigation.
                await asyncio.sleep(self.RETRY_DELAY_SECONDS)

    async def _send_completion(self, messages, model, *, tools=None, response_schema=None, timeout=TIMEOUT_SECONDS):
        ensure(self.enabled, 'NVIDIA_KEY_REQUIRED', 409)
        kwargs = dict(model=model, messages=messages, temperature=0,
                      max_tokens=1500 if tools is not None else 1000, stream=False)
        extra = self.generation_options(model)
        if tools is None:
            if response_schema is not None:
                # Use the SDK extension for the full NIM JSON Schema contract.
                extra['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': 'structured_response', 'strict': True, 'schema': response_schema}}
            else:
                kwargs['response_format'] = {'type': 'json_object'}
        else:
            # SDK 1.5.0 annotates tools as strings despite the NIM JSON schema.
            # Its documented extra_body extension preserves actual function tools.
            extra = {**extra, 'tools': tools}
            kwargs['tool_choice'] = 'auto'
        try:
            async with asyncio.timeout(timeout):
                value = await self._client().chat.completions.create(**kwargs, extra_body=extra, timeout=timeout)
            result = value.model_dump(mode='json') if hasattr(value, 'model_dump') else value
            ensure(isinstance(result, dict), 'NIM_INVALID_RESPONSE', 502)
            ensure(len(json.dumps(result, ensure_ascii=False)) < LIMIT, 'PROVIDER_RESPONSE_LIMIT', 502)
            choices = result.get('choices')
            ensure(isinstance(choices, list) and bool(choices) and isinstance(choices[0], dict), 'NIM_INVALID_RESPONSE', 502)
            choice = choices[0]
            ensure(isinstance(choice.get('finish_reason'), str) and isinstance(choice.get('message'), dict), 'NIM_INVALID_RESPONSE', 502)
            usage = result.get('usage') if isinstance(result.get('usage'), dict) else {}
            record('provider.response', category='nim', finish_reason=choice['finish_reason'],
                   **{name: usage.get(name) for name in ('prompt_tokens', 'completion_tokens', 'total_tokens')})
            return {'finish_reason': choice['finish_reason'], 'message': choice['message']}
        except (APITimeoutError, TimeoutError):
            raise AppError('NIM_TIMEOUT', 504) from None
        except APIStatusError as exc:
            record('provider.response', category='nim', status=exc.status_code)
            raise _nim_error(exc.status_code) from None
        except APIConnectionError:
            raise AppError('NIM_UNAVAILABLE', 502) from None
        except (ValueError, TypeError, AttributeError):
            raise AppError('NIM_INVALID_RESPONSE', 502) from None

    async def chat(self, messages, model=None, *, response_schema=None, timeout=TIMEOUT_SECONDS):
        result = await self._completion(messages, model or self.model, response_schema=response_schema, timeout=timeout)
        ensure(result['finish_reason'] == 'stop', 'NIM_INCOMPLETE_RESPONSE', 502)
        content = result['message'].get('content')
        ensure(isinstance(content, str) and bool(content.strip()), 'NIM_INVALID_RESPONSE', 502)
        try:
            json.loads(content)
        except ValueError:
            raise AppError('NIM_INVALID_JSON', 502) from None
        return content

    async def complete(self, messages, tools):
        return await self._completion(messages, self.model, tools=tools)

    async def close(self):
        if self._sdk is not None:
            await self._sdk.close()


class Drugs:
    BASE = 'https://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService08/'

    def __init__(self, env=os.environ, transport=None):
        from urllib.parse import unquote
        self.key = unquote((env.get('MFDS_API_KEY') or '').strip())
        self._http = httpx.AsyncClient(transport=transport, timeout=30, follow_redirects=False)

    @property
    def enabled(self):
        return bool(self.key)

    async def _items(self, operation, **params):
        ensure(self.enabled, 'MFDS_KEY_REQUIRED', 409)
        raw = await _json_request(self._http, 'GET', self.BASE + operation, service='MFDS',
            params={'serviceKey': self.key, 'pageNo': '1', 'numOfRows': '30', 'type': 'json', **params})
        ensure(isinstance(raw, dict), 'MFDS_REQUEST_FAILED', 502)
        result = raw.get('response', raw)
        ensure(isinstance(result, dict), 'MFDS_REQUEST_FAILED', 502)
        header = result.get('header') or {}
        ensure(isinstance(header, dict), 'MFDS_REQUEST_FAILED', 502)
        code = str(header.get('resultCode'))
        if code in {'20', '30', '31'}:
            raise AppError('MFDS_AUTH_FAILED', 502)
        if code in {'22', '23'}:
            raise AppError('MFDS_RATE_LIMIT', 429)
        ensure(code in {'00', '0'}, 'MFDS_REQUEST_FAILED', 502)
        body = result.get('body') or {}
        ensure(isinstance(body, dict), 'MFDS_REQUEST_FAILED', 502)
        items = body.get('items') or []
        if isinstance(items, dict):
            items = items.get('item', items)
        if isinstance(items, dict):
            items = [items] if items else []
        ensure(isinstance(items, list) and len(items) <= 30 and all(isinstance(x, dict) for x in items), 'MFDS_REQUEST_FAILED', 502)
        try:
            total = int(body.get('totalCount') or 0)
        except (ValueError, TypeError):
            raise AppError('MFDS_REQUEST_FAILED', 502) from None
        return items, total

    @staticmethod
    def _product(item):
        identifier = str(item.get('ITEM_SEQ', ''))
        ensure(bool(re.fullmatch(r'\d{5,20}', identifier)) and isinstance(item.get('ITEM_NAME'), str), 'MFDS_INVALID_PRODUCT', 502)
        ingredient = item.get('MAIN_ITEM_INGR') or item.get('ITEM_INGR_NAME') or ''
        ensure(isinstance(ingredient, str), 'MFDS_INVALID_PRODUCT', 502)
        return {'id': identifier, 'name': item['ITEM_NAME'], 'ingredients': ingredient,
                'manufacturer': item.get('ENTP_NAME'), 'permitDate': item.get('ITEM_PERMIT_DATE'),
                'cancelDate': item.get('CANCEL_DATE') or None,
                'url': 'https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=' + identifier,
                'retrievedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}

    async def lookup(self, name):
        ensure(isinstance(name, str) and 2 <= len(name) <= 120, 'INVALID_DRUG_NAME')
        items, total = await self._items('getDrugPrdtPrmsnInq08', item_name=name)
        products = [self._product(item) for item in items]
        return {'products': products, 'total': total, 'truncated': total > len(products), 'requiresSelection': True,
                'source': 'https://www.data.go.kr/data/15095677/openapi.do'}

    async def ingredients(self, identifier):
        ensure(isinstance(identifier, str) and bool(re.fullmatch(r'\d{5,20}', identifier)), 'INVALID_DRUG_ID')
        items, total = await self._items('getDrugPrdtMcpnDtlInq08', Item_seq=identifier)
        ensure(total == len(items) and all(str(x.get('ITEM_SEQ')) == identifier for x in items), 'MFDS_PRODUCT_MISMATCH', 502)
        return items

    async def detail(self, identifier):
        ensure(isinstance(identifier, str) and bool(re.fullmatch(r'\d{5,20}', identifier)), 'INVALID_DRUG_ID')
        items, total = await self._items('getDrugPrdtPrmsnDtlInq08', item_seq=identifier)
        ensure(total == 1 and len(items) == 1 and str(items[0].get('ITEM_SEQ')) == identifier, 'MFDS_PRODUCT_MISMATCH', 502)
        item = items[0]
        documents = {k: item.get(k) or '' for k in ('MAIN_ITEM_INGR', 'ITEM_INGR_NAME', 'EE_DOC_DATA', 'UD_DOC_DATA', 'NB_DOC_DATA', 'PN_DOC_DATA')}
        ensure(all(isinstance(x, str) and len(x) <= 1_000_000 for x in documents.values()), 'MFDS_DOCUMENT_LIMIT', 502)
        if not documents['MAIN_ITEM_INGR'] and not documents['ITEM_INGR_NAME']:
            for i, row in enumerate(await self.ingredients(identifier)):
                value = row.get('MTRAL_NM')
                ensure(isinstance(value, str), 'MFDS_INVALID_PRODUCT', 502)
                documents[f'MTRAL_NM:{i}'] = value
        return {'product': self._product(item), 'documents': documents,
                'changeDate': item.get('CHANGE_DATE'), 'status': item.get('CANCEL_NAME'),
                'retrievedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}

    async def close(self):
        await self._http.aclose()
