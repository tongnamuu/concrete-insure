"""Synthetic MFDS HTTP responses for tests only; no production fallback."""
import json
from pathlib import Path
import httpx
from concreteinsure.providers import Drugs
from tests.nim_fixture import ScriptedNim

ITEM_ID = '202012345'
NAME = '조플루자정20밀리그램'

def xml(*texts):
    return '<DOC><SECTION>' + ''.join('<PARAGRAPH><![CDATA['+t+']]></PARAGRAPH>' for t in texts) + '</SECTION></DOC>'

def row(identifier=ITEM_ID, name=NAME):
    # Read a fresh object so individual test mutations cannot leak to other tests.
    value = json.loads((Path(__file__).parent / 'fixtures/mfds-product.json').read_text(encoding='utf-8'))
    value.update(ITEM_SEQ=identifier, ITEM_NAME=name)
    return value


def response(items, total=None, code='00'):
    return httpx.Response(200, json={'header':{'resultCode':code},'body':{'items':items,'totalCount':len(items) if total is None else total}})

def provider(requests=None):
    def handle(request):
        if requests is not None:requests.append(request)
        if request.url.path.endswith('getDrugPrdtPrmsnInq08'):
            return response([row(), row('202012346','조플루자정40밀리그램')])
        return response([row(request.url.params['item_seq'])])
    return Drugs(env={'MFDS_API_KEY':'test-only'},transport=httpx.MockTransport(handle))

class DrugNim(ScriptedNim):
    async def chat(self,messages,model=None,**kwargs):
        value=json.loads(await super().chat(messages,model,**kwargs))
        payload=json.loads(messages[-1]['content'])
        original=payload.get('query','')+payload.get('description','')
        value['drugNames']=['조플루자'] if '조플루자' in original else []
        return json.dumps(value,ensure_ascii=False)

    async def complete(self, messages, tools):
        if not any(t['function']['name'].startswith('medicine__') for t in tools):
            return await super().complete(messages, tools)
        assert all(t['function']['name'] != 'medicine__finish_evidence' for t in tools)
        self.calls.append('drug_complete')
        payload = json.loads(next(m['content'] for m in messages if m['role'] == 'user'))
        done = [(m['tool_calls'][0]['function']['name'], json.loads(m['tool_calls'][0]['function']['arguments']))
                for m in messages if m['role'] == 'assistant' and m.get('tool_calls')]
        steps = [('lookup_products', {'name_id': n['name_id']}) for n in payload['names']]
        if not payload['requiresSelection']:
            steps = [(name, {'product_id': p['product_id']}) for p in payload['selectedProducts']
                     for name in ('inspect_ingredients', 'inspect_label')]
        name, args = next((name, args) for name, args in steps if ('medicine__'+name, args) not in done)
        return {'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'drug-'+str(len(done)), 'type': 'function', 'function': {'name': 'medicine__'+name, 'arguments': json.dumps(args)}}]}}
