import test from 'node:test';
import assert from 'node:assert/strict';
import { literalTerms,querySchema,groundedTerms } from '../src/core.js';
import { understandInput,understandInputWithModel } from '../src/agents/input.js';

test('brand prescription sentence keeps brand without deriving disease/ingredient',()=>{
 const terms=literalTerms('조플루자를 처방받았습니다.');
 assert.deepEqual(terms,['조플루자']);
 assert.ok(!terms.includes('독감')&&!terms.includes('발록사비르'));
});
test('generic retry produces no unrelated search terms',()=>{
 assert.deepEqual(literalTerms('다시 확인해주세요. 해당하는 사안이 있을텐데'),[]);
 assert.deepEqual(literalTerms('조플루자를 처방받았다고 했는데 안되는데? 실제로 대상이야'),['조플루자']);
});
test('exact Korean stems and diagnosis codes survive punctuation',()=>{
 assert.deepEqual(literalTerms('당뇨에 관한 약관 찾아줘. J10.1, E11.9.'),['당뇨','J10.1','E11.9']);
 const query='오셀타미비르를 처방받았어요. 타미플루에서 확인해주세요.';
 const terms=literalTerms(query);assert.deepEqual(terms,['오셀타미비르','타미플루']);
 assert.ok(terms.every(term=>query.includes(term)));
});
test('description-only requests remain valid and description contributes terms',()=>{
 const request=querySchema.parse({description:'조플루자를 처방받았습니다.'});
 assert.equal(request.query,'');assert.equal(understandInput(request).description,request.description);
 assert.deepEqual(understandInput(request).terms,['조플루자']);
 assert.deepEqual(understandInput({query:'다시 확인해주세요.',description:'당뇨에 관한 내용',confirmedTerms:['J10.1']}).terms,['J10.1','당뇨']);
});
test('explicit confirmed entries stay unchanged even if generic or one character',()=>{
 assert.deepEqual(literalTerms('다시 확인해주세요.',['처방','J10.1','약']),['처방','J10.1','약']);
});
test('model terms remain grounded in original description; generic followup is removed',async()=>{
 const result=await understandInputWithModel({query:'다시 확인해주세요.',description:'조플루자를 처방받았습니다.',cloudConsent:true},{nim:{enabled:true,chat:async()=>JSON.stringify({terms:['조플루자','다시']})}});
 assert.deepEqual(result.terms,['조플루자']);
 assert.throws(()=>groundedTerms('{"terms":["독감"]}','다시 확인해주세요.',[],'조플루자를 처방받았습니다.'),/UNGROUNDED_TERM/);
});
