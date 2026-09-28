import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startPythonTestServer,python} from './python-test-server.mjs';
import {acceptConsent} from './consent-test-helper.mjs';
import {ready,emptySession,restoredSession} from './browser-session-helper.mjs';
const temp=await mkdtemp(path.join(os.tmpdir(),'concreteinsure-reset-'));
const root=path.join(temp,'data'),pdf=path.join(temp,'policy.pdf');
execFileSync(python,['-c',"import pymupdf as f,sys;d=f.open();p=d.new_page();p.insert_text((50,100),'독감 항바이러스제 발록사비르 oseltamivir',fontname='korea');d.save(sys.argv[1])",pdf]);
const server=await startPythonTestServer(root,'tests.browser_server:create_reset_test_app');
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})}).catch(async error=>{await server.close();await rm(temp,{recursive:true,force:true});throw error;});
const context=await browser.newContext(),page=await context.newPage(),errors=[];
page.on('pageerror',e=>errors.push(e.message));
async function upload(){await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});await expect(page.locator('#progress')).toBeHidden();}
async function send(query){await page.locator('#query').fill(query);await page.locator('#send').click();await acceptConsent(page);}
async function snapshot(){
 const id=await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case'));
 const response=await page.request.get(`${server.base}/api/cases/${id}`);assert.equal(response.status(),200);
 return {id,jobs:(await response.json()).jobs.map(j=>j.id)};
}
async function removed(saved){
 assert.equal((await page.request.get(`${server.base}/api/cases/${saved.id}`)).status(),404);
 for(const id of saved.jobs)assert.equal((await page.request.get(`${server.base}/api/jobs/${id}`)).status(),404);
 execFileSync(python,['-c',`import sqlite3,sys,json
from pathlib import Path
root=Path(sys.argv[1]);case=sys.argv[2];jobs=json.loads(sys.argv[3])
assert not (root/case).exists()
with sqlite3.connect(root/'store.sqlite') as db:
 for table,column in [('cases','id'),('jobs','case_id'),('conversations','case_id'),('selection_checkpoints','case_id')]:
  assert db.execute(f'SELECT count(*) FROM {table} WHERE {column}=?',(case,)).fetchone()[0]==0
 for job in jobs:
  for table in ['turns','events']:
   assert db.execute(f'SELECT count(*) FROM {table} WHERE job_id=?',(job,)).fetchone()[0]==0`,root,saved.id,JSON.stringify(saved.jobs)]);
 assert.deepEqual(await page.evaluate(()=>[...Object.keys(sessionStorage),...Object.keys(localStorage)].filter(k=>['concrete-insure-','insure-lens-'].some(prefix=>k.startsWith(prefix)))),[]);
}
const mutations=[];
page.on('request',request=>{if(['POST','DELETE'].includes(request.method())&&!request.url().includes('/_test/'))mutations.push(request.url());});
async function calls(){const response=await page.request.get(`${server.base}/_test/calls`);assert.equal(response.status(),200);const data=await response.json();assert.equal(typeof data.input,'number');return data;}
async function conversation(){const {id}=await snapshot();return (await page.request.get(`${server.base}/api/cases/${id}/conversation`)).json();}
async function restored(saved){
 await restoredSession(page);
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case')),saved.id);
 assert.deepEqual((await snapshot()).jobs,saved.jobs);
}
async function clear(){page.once('dialog',dialog=>dialog.accept());await page.locator('#clearCase').click();await emptySession(page);}
try{
 await page.goto(server.base);await emptySession(page);await upload();
 const other=await context.newPage();await other.goto(server.base);await ready(other);
 await other.locator('#policyFile').setInputFiles(pdf);await expect(other.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});await expect(other.locator('#progress')).toBeHidden();
 const otherId=await other.evaluate(()=>sessionStorage.getItem('concrete-insure-case'));
 await send('조플루자를 처방받았어요');await expect(page.locator('.drug-selection')).toBeVisible({timeout:30000});await expect(page.locator('#progress')).toBeHidden();
 let saved=await snapshot(),before=await calls(),mutationCount=mutations.length;
 const pendingConversation=await conversation();
 await page.evaluate(()=>localStorage.setItem('unrelated-setting','preserve'));
 await page.reload();await restored(saved);
 await expect(page.locator('.user-message')).toHaveCount(1);await expect(page.locator('.drug-selection')).toBeVisible();
 assert.equal((await conversation()).id,pendingConversation.id);
 assert.deepEqual(await calls(),before);assert.equal(mutations.length,mutationCount);
 assert.equal((await page.request.get(`${server.base}/api/cases/${otherId}`)).status(),200);
 assert.equal(await page.evaluate(()=>localStorage.getItem('unrelated-setting')),'preserve');

 // A failed read retains the pointer and blocks new submissions; retry never deletes data.
 let failRead=true;
 await page.route(`**/api/cases/${saved.id}`,route=>route.request().method()==='GET'&&failRead?route.fulfill({status:503,contentType:'application/json',body:'{"error":"REQUEST_FAILED"}'}):route.continue());
 await page.reload();await expect(page.locator('#retryRestore')).toBeVisible();
 for(const id of ['send','policyFile','drugName','clearCase'])await expect(page.locator('#'+id)).toBeDisabled();
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case')),saved.id);
 failRead=false;await page.locator('#retryRestore').click();await restored(saved);await page.unroute(`**/api/cases/${saved.id}`);
 assert.equal(mutations.length,mutationCount);

 // A restored product checkpoint resumes only after a fresh explicit consent.
 await page.locator('.drug-selection input[type=checkbox]').first().check();
 await page.getByRole('button',{name:'선택한 제품으로 계속'}).click();await expect(page.locator('#cloudConsent')).not.toBeChecked();
 await page.locator('#cancelConsent').click();assert.equal(mutations.length,mutationCount);
 await page.getByRole('button',{name:'선택한 제품으로 계속'}).click();await acceptConsent(page);
 await expect(page.locator('.investigation-result')).toBeVisible({timeout:30000});await expect(page.locator('#progress')).toBeHidden();
 await page.locator('.quote-card button').first().click();await expect(page.locator('#highlights polygon').first()).toBeAttached();
 const quotes=await page.locator('.quote-card blockquote').allTextContents();
 await page.locator('#query').fill('아직 보내지 않은 질문');
 saved=await snapshot();before=await calls();mutationCount=mutations.length;
 await page.reload();await restored(saved);
 assert.deepEqual(await page.locator('.quote-card blockquote').allTextContents(),quotes);
 await expect(page.locator('#download')).toBeEnabled();await expect(page.locator('#query')).toHaveValue('');
 await page.locator('.quote-card button').first().click();await expect(page.locator('#highlights polygon').first()).toBeAttached();
 assert.deepEqual(await calls(),before);assert.equal(mutations.length,mutationCount);

 // Another browser owner cannot recover a case merely by copying its opaque ID.
 const stranger=await browser.newContext(),foreign=await stranger.newPage();
 await foreign.goto(server.base);await ready(foreign);
 await foreign.evaluate(id=>sessionStorage.setItem('concrete-insure-case',id),saved.id);
 await foreign.reload();await emptySession(foreign);
 assert.equal(await foreign.evaluate(()=>sessionStorage.getItem('concrete-insure-case')),null);
 assert.equal((await page.request.get(`${server.base}/api/cases/${saved.id}`)).status(),200);
 await stranger.close();

 // The same running request survives reload; another tab's queued request does too.
 await send('독감 대기');await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 saved=await snapshot();const active=await conversation();before=await calls();mutationCount=mutations.length;
 await other.locator('#query').fill('독감');await other.locator('#send').click();await acceptConsent(other);
 await expect(other.locator('.user-message')).toHaveCount(1);
 const queuedBefore=await (await other.request.get(`${server.base}/api/cases/${otherId}/conversation`)).json();
 assert.equal(queuedBefore.turns[0].state,'queued');
 await other.reload();await expect(other.locator('.user-message')).toHaveCount(1);await expect(other.locator('#progress')).toBeVisible();
 await page.reload();await expect(page.locator('.user-message').last()).toHaveText('독감 대기');
 await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 for(const id of ['send','query','policyFile','clearResults'])await expect(page.locator('#'+id)).toBeDisabled();
 assert.equal((await conversation()).turns.at(-1).jobId,active.turns.at(-1).jobId);
 assert.equal((await conversation()).id,active.id);assert.equal(mutations.length,mutationCount);assert.deepEqual(await calls(),before);
 assert.equal((await page.request.post(`${server.base}/_test/release`,{headers:{'X-Local-Request':'1'}})).status(),200);
 await expect(page.locator('#progress')).toBeHidden({timeout:30000});await expect(page.locator('.investigation-result')).toHaveCount(2);
 await expect(other.locator('#progress')).toBeHidden({timeout:30000});await expect(other.locator('.investigation-result')).toHaveCount(1);
 assert.equal((await conversation()).turns.at(-1).jobId,active.turns.at(-1).jobId);
 const queuedAfter=await (await other.request.get(`${server.base}/api/cases/${otherId}/conversation`)).json();
 assert.equal(queuedAfter.turns[0].jobId,queuedBefore.turns[0].jobId);assert.equal(queuedAfter.turns[0].state,'completed');
 // Opening the stream after completion still retrieves exactly the existing result.
 saved=await snapshot();before=await calls();mutationCount=mutations.length;await page.reload();await restored(saved);
 await expect(page.locator('.investigation-result')).toHaveCount(2);assert.deepEqual(await calls(),before);assert.equal(mutations.length,mutationCount);

 // Failed and cancelled requests retain the original question after reload.
 await send('실패 검사');await expect(page.locator('#progress')).toBeHidden({timeout:30000});
 saved=await snapshot();before=await calls();await page.reload();await restored(saved);
 await expect(page.locator('.assistant-message').last()).toContainText('검색 응답 시간이 초과');assert.deepEqual(await calls(),before);
 await page.locator('.assistant-message').last().getByRole('button',{name:'다시 입력하기'}).click();await expect(page.locator('#query')).toHaveValue('실패 검사');
 await send('독감 취소 대기');await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 await page.reload();await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 await page.locator('#cancelJob').click();await expect(page.locator('#progress')).toBeHidden({timeout:10000});
 saved=await snapshot();await page.reload();await restored(saved);await expect(page.locator('.assistant-message').last()).toContainText('요청을 취소했습니다.');

 // Old brand/storage pointers migrate without deleting or rerunning the request.
 for(const storageName of ['sessionStorage','localStorage']){
  const owner=(await context.cookies(server.base)).find(cookie=>cookie.name==='concreteinsure_session');
  await context.clearCookies({name:'concreteinsure_session'});await context.addCookies([{...owner,name:'insurelens_session'}]);
  await page.evaluate(storageName=>{const id=sessionStorage.getItem('concrete-insure-case');sessionStorage.removeItem('concrete-insure-case');window[storageName].setItem('insure-lens-case',id);},storageName);
  before=await calls();mutationCount=mutations.length;await page.reload();await restored(saved);
  assert.equal((await context.cookies(server.base)).find(cookie=>cookie.name==='concreteinsure_session').value,owner.value);
  assert.equal(await page.evaluate(storageName=>window[storageName].getItem('insure-lens-case'),storageName),null);
  assert.deepEqual(await calls(),before);assert.equal(mutations.length,mutationCount);
 }
 await page.evaluate(()=>{localStorage.setItem('concrete-insure-case',sessionStorage.getItem('concrete-insure-case'));sessionStorage.removeItem('concrete-insure-case');});
 await page.reload();await restored(saved);assert.equal(await page.evaluate(()=>localStorage.getItem('concrete-insure-case')),null);

 // Only explicit clearing cancels running work and deletes files/records.
 await send('독감 취소 대기');await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 saved=await snapshot();await clear();await removed(saved);
 assert.equal((await page.request.get(`${server.base}/api/cases/${otherId}`)).status(),200);await other.close();
 await upload();await send('독감');await expect(page.locator('.investigation-result')).toBeVisible({timeout:30000});await expect(page.locator('#progress')).toBeHidden();
 saved=await snapshot();let failDelete=true;
 await page.route(`**/api/cases/${saved.id}`,route=>route.request().method()==='DELETE'&&failDelete?route.fulfill({status:503,contentType:'application/json',body:'{"error":"REQUEST_FAILED"}'}):route.continue());
 page.once('dialog',dialog=>dialog.accept());await page.locator('#clearCase').click();await expect(page.locator('#error')).toBeVisible();
 await page.reload();await restored(saved);failDelete=false;await clear();await removed(saved);await page.unroute(`**/api/cases/${saved.id}`);

 // A stale/deleted pointer resets only the local screen; it cannot resurrect deleted data.
 await upload();saved=await snapshot();await page.request.delete(`${server.base}/api/cases/${saved.id}`,{headers:{'X-Local-Request':'1'}});
 await page.reload();await emptySession(page);await removed(saved);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,restorePendingSelection:true,restoreEvidence:true,runningAndQueuedRequestsSurvive:true,sameJobAndConversation:true,noDuplicateInference:true,consentRequiredForResume:true,failedAndCancelledRequestsRestored:true,restoreFailureRetry:true,ownershipEnforced:true,legacyPointerMigration:true,explicitClearRemovesFilesAndRecords:true,unrelatedTabPreserved:true,stalePointerHandled:true,browserErrors:errors}));
}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
