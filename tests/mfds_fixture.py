"""Synthetic MFDS HTTP responses for tests only; no production fallback."""
import json
import httpx
from insurelens.providers import Drugs
from tests.nim_fixture import ScriptedNim

ITEM_ID = '202012345'
NAME = '조플루자정20밀리그램'

def xml(*texts):
    return '<DOC><SECTION>' + ''.join('<PARAGRAPH><![CDATA['+t+']]></PARAGRAPH>' for t in texts) + '</SECTION></DOC>'

def row(identifier=ITEM_ID, name=NAME):
    return {'ITEM_SEQ':identifier, 'ITEM_NAME':name, 'ENTP_NAME':'가상 시험 업체',
            'ITEM_INGR_NAME':'Baloxavir Marboxil', 'MAIN_ITEM_INGR':'[TEST01]발록사비르 마르복실',
            'ITEM_PERMIT_DATE':'20200101', 'CHANGE_DATE':'20260101', 'CANCEL_NAME':'정상',
            'EE_DOC_DATA':xml('1. 인플루엔자 감염증의 치료', '시험용 치료 조건 원문.', '2. 노출 후 인플루엔자 감염증의 예방'),
            'NB_DOC_DATA':'', 'PN_DOC_DATA':xml('시험용 문장: 이 약은 전구약물로 활성 대사물 발록사비르로 전환된다.')}

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
