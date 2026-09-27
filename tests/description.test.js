import test from 'node:test';
import assert from 'node:assert/strict';
import {querySchema} from '../src/core.js';
import {understandInput,understandInputWithModel} from '../src/agents/input.js';
import {runInvestigation} from '../src/agent.js';
const description='  조카가 독감 진단을 받았고 조플루자를 처방받았어요.\n처방전은 없어요.  ';
test('description replaces prescription and question; raw text is preserved',()=>{
 const parsed=querySchema.parse({description});assert.equal(parsed.query,'');assert.equal(parsed.description,description);assert.deepEqual(parsed.confirmedTerms,[]);
 const input=understandInput(parsed);assert.equal(input.description,description);assert(input.terms.includes('독감'));assert(input.terms.includes('조플루자'));assert(!input.terms.includes('발록사비르'));
});
test('empty input, oversized description and unrecognized fields are rejected',()=>{
 for(const value of [{},{query:' ',description:'\n '},{description:'a'.repeat(4001)},{description:'독감',diagnosis:'verified'}])assert.equal(querySchema.safeParse(value).success,false);
});
test('NIM receives original explanation and may select its exact substrings',async()=>{
 const out=await understandInputWithModel({description,cloudConsent:true},{nim:{enabled:true,chat:async(messages)=>{const data=JSON.parse(messages.at(-1).content);assert.equal(data.description,description);assert.equal(data.query,'');return '{"terms":["독감","조플루자"]}';}}});
 assert.deepEqual(out.terms,['독감','조플루자']);assert.equal(out.description,description);
});
test('symptom or medicine explanation cannot become a model-invented diagnosis',async()=>{
 await assert.rejects(()=>understandInputWithModel({description:'열이 나고 기침을 해요. 조플루자를 먹었어요.',cloudConsent:true},{nim:{enabled:true,chat:async()=>'{"terms":["독감"]}'}}),/UNGROUNDED_TERM/);
});
test('description-only investigation returns trusted original, not narrative or diagnosis',async()=>{
 const source={id:'1:0:2',page:1,start:0,end:2,sourceStart:0,sourceEnd:5,quote:'독감 원문',matchedText:'독감',segments:[{index:0,start:0,end:1,quad:[0,0,1,0,1,1,0,1]}],documentHash:'abc',offsetEncoding:'unicode-code-points'};
 const result=await runInvestigation({document:{pdf:'/trusted',index:'/trusted'},request:{description}}, {retrieve:async({terms,ids})=>({hits:ids.some(i=>terms[i]==='독감')?[source]:[],truncated:false}),context:async()=>({hits:[],truncated:false})});
 assert.deepEqual(result.quotes,[source]);assert.deepEqual(result.mappings,[]);assert(!('diagnosis' in result));assert(!('answer' in result));
});
