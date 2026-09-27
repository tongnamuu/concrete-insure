import test from 'node:test';import assert from 'node:assert/strict';import {mkdtemp,rm} from 'node:fs/promises';import os from 'node:os';import path from 'node:path';import {execFileSync} from 'node:child_process';
import {createApp} from '../src/server.js';
const fixture=()=>execFileSync(new URL('../.venv/bin/python',import.meta.url).pathname,['-c',"import pymupdf as f,sys;d=f.open();p=d.new_page();p.insert_text((50,100),'보험약관 독감 항바이러스제',fontname='korea');p.insert_text((50,130),'오셀타미비르',fontname='korea');sys.stdout.buffer.write(d.tobytes())"]);
async function setup(){const root=await mkdtemp(path.join(os.tmpdir(),'insurelens-http-'));const nim={enabled:false};const state=createApp({root,nim,drugs:{key:'',lookup:async()=>{throw Error('not used');}}});const server=state.app.listen(0,'127.0.0.1');await new Promise(r=>server.once('listening',r));const base=`http://127.0.0.1:${server.address().port}`;let cookie='';async function req(url,options={}){const response=await fetch(base+url,{...options,headers:{'X-Local-Request':'1',cookie,...options.headers}});if(response.headers.get('set-cookie'))cookie=response.headers.get('set-cookie').split(';')[0];return response;}
 return {...state,base,req,cleanup:async()=>{await state.queue.tail;server.closeAllConnections();await new Promise(r=>server.close(r));state.store.close();await rm(root,{recursive:true,force:true});}};}
async function wait(req,id){for(let n=0;n<100;n++){const j=await(await req('/api/jobs/'+id)).json();if(['completed','failed','cancelled'].includes(j.state))return j;await new Promise(r=>setTimeout(r,50));}throw Error('timed out');}
test('full local upload -> resumable SSE -> verbatim investigation -> annotated download, isolation and delete',async()=>{const s=await setup();try{
 const c=await(await s.req('/api/cases',{method:'POST'})).json();assert(c.id);
 const unauthorized=await fetch(s.base+'/api/cases/'+c.id);assert.equal(unauthorized.status,404);
 const form=new FormData();form.set('file',new Blob([fixture()],{type:'application/pdf'}),'my.pdf');
 const upload=await s.req(`/api/cases/${c.id}/documents`,{method:'POST',body:form});assert.equal(upload.status,202);const {jobId}=await upload.json();
 const stream=await(await s.req('/api/jobs/'+jobId+'/events')).text();assert.match(stream,/event: completed/);assert.match(stream,/id: \d+/);
 const doc=(await wait(s.req,jobId)).result.document;assert.equal(doc.pages,1);
 const payload={query:'독감걸렸는데 관련 내용찾아줘',confirmedTerms:[],drugIds:[],cloudConsent:false,translation:false};
 const r=await s.req(`/api/cases/${c.id}/investigations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});assert.equal(r.status,202);const id=(await r.json()).jobId;
 const job=await wait(s.req,id);assert.equal(job.state,'completed',JSON.stringify(job));assert(job.result.quotes.some(x=>x.quote.includes('독감')));assert(job.result.quotes.some(x=>x.quote.includes('오셀타미비르')));assert(!('answer' in job.result));
 const pdf=await s.req(`/api/jobs/${id}/annotated.pdf`);assert.equal(pdf.status,200);assert.equal(Buffer.from(await pdf.arrayBuffer()).subarray(0,5).toString(),'%PDF-');
 const description='조카가 독감 진단을 받았어요. 처방전은 없어요.';
 const described=await s.req(`/api/cases/${c.id}/investigations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description})});assert.equal(described.status,202);
 const descriptionJob=await wait(s.req,(await described.json()).jobId);assert.equal(descriptionJob.state,'completed');assert(descriptionJob.result.quotes.some(x=>x.quote.includes('독감')));
 const bad=await s.req(`/api/cases/${c.id}/investigations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,drugIds:['200001234']})});assert.equal(bad.status,400);
 const csrf=await fetch(s.base+'/api/cases',{method:'POST'});assert.equal(csrf.status,403);
 await s.req('/api/cases/'+c.id,{method:'DELETE'});assert.equal((await s.req('/api/jobs/'+id)).status,404);
 }finally{await s.cleanup();}});
test('text prescription PDF upload returns draft; arbitrary images require consent/config',async()=>{const s=await setup();try{const c=await(await s.req('/api/cases',{method:'POST'})).json();let form=new FormData();form.set('file',new Blob([fixture()]),'rx.pdf');const r=await s.req(`/api/cases/${c.id}/ocr`,{method:'POST',body:form});assert.equal(r.status,202);const j=await wait(s.req,(await r.json()).jobId);assert.equal(j.result.requiresConfirmation,true);assert(j.result.text.includes('오셀타미비르'));form=new FormData();form.set('file',new Blob(['fake']),'rx.png');assert.equal((await s.req(`/api/cases/${c.id}/ocr`,{method:'POST',body:form})).status,409);}finally{await s.cleanup();}});
