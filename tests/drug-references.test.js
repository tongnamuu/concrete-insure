import test from 'node:test';import assert from 'node:assert/strict';
import {resolveDrugReferences,verifyDrugReferences} from '../src/agents/drug-references.js';
import {runInvestigation} from '../src/agent.js';import {pdfOperation} from '../src/pdf.js';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';import {execFileSync} from 'node:child_process';import os from 'node:os';import path from 'node:path';
test('brand resolves source-backed ingredient and related concept, not patient diagnosis',()=>{
 const r=resolveDrugReferences({description:'조플루자를 처방받았습니다.'});assert.equal(r.references.length,1);assert(r.specificTerms.includes('발록사비르'));assert(r.contextTerms.includes('인플루엔자'));assert.equal(r.references[0].scope,'product_reference');for(const ref of r.references)for(const f of ref.facts)for(const term of f.terms)assert(f.quote.includes(term));
});
test('unknown brands and prefixed lookalikes do not invent references',()=>{
 for(const description of ['없는약품을 처방받았습니다.','가짜조플루자'])assert.deepEqual(resolveDrugReferences({description}).references,[]);
 assert(resolveDrugReferences({description:'타미플루를 처방받았어요.'}).specificTerms.includes('오셀타미비르'));
});
test('reference text tampering is rejected',()=>{
 const r=resolveDrugReferences({query:'조플루자'}).references;assert.doesNotThrow(()=>verifyDrugReferences(r));r[0].facts[0].quote='invented ingredient';assert.throws(()=>verifyDrugReferences(r),/UNVERIFIED_DRUG_REFERENCE/);
});
test('brand-only request finds nearby original clauses and update notice, excludes generic followup text',async()=>{
 const folder=await mkdtemp(path.join(os.tmpdir(),'insurelens-drug-'));try{
 const pdf=path.join(folder,'policy.pdf'),index=path.join(folder,'index.gz');
 const code="import pymupdf as f,sys;d=f.open();p=d.new_page();p.insert_text((40,80),'다시 확인해주세요 해당하는 사안 일반 안내',fontname='korea');p=d.new_page();p.insert_text((40,80),'독감(인플루엔자) 항바이러스제 특별약관',fontname='korea');p.insert_text((40,130),'보험금의 지급사유: 인플루엔자 치료를 목적으로 처방받은 경우',fontname='korea');p=d.new_page();p.insert_text((40,80),'성분 안내: 발록사비르(baloxavir)',fontname='korea');p.insert_text((40,130),'2020년 7월 기준, 신규 허가 또는 허가 취소시 변경될 수 있습니다.',fontname='korea');sys.stdout.buffer.write(d.tobytes())";
 await writeFile(pdf,execFileSync(new URL('../.venv/bin/python',import.meta.url).pathname,['-c',code]));const meta=await pdfOperation({op:'index',pdf,index});
 const result=await runInvestigation({document:{pdf,index,...meta},request:{description:'조플루자를 처방받았습니다.',query:'다시 확인해주세요. 해당하는 사안이 있을텐데'},nim:{enabled:false}});
 assert.equal(result.references[0].brand,'조플루자');assert.deepEqual(result.mappings,[]);assert(result.quotes.some(h=>h.page===2&&h.quote.includes('지급사유')));assert(result.quotes.some(h=>h.page===3&&h.quote.includes('신규 허가')));assert(result.quotes.every(h=>h.page!==1));assert(!result.terms.includes('사안'));
 const saved=await pdfOperation({op:'annotate',pdf,index,hits:result.quotes,output:path.join(folder,'out.pdf')});assert(saved.count>0);
 }finally{await rm(folder,{recursive:true,force:true});}
});
