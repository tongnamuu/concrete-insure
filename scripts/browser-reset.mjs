import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startPythonTestServer,python} from './python-test-server.mjs';
import {acceptConsent} from './consent-test-helper.mjs';
import {ready,emptySession} from './browser-session-helper.mjs';
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
try{
 await page.goto(server.base);await emptySession(page);await upload();
 // A separate tab's new case must not be deleted by this tab's refresh.
 const other=await context.newPage();await other.goto(server.base);await ready(other);
 await other.locator('#policyFile').setInputFiles(pdf);await expect(other.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});
 const otherId=await other.evaluate(()=>sessionStorage.getItem('concrete-insure-case'));
 await send('조플루자를 처방받았어요');await expect(page.locator('.drug-selection')).toBeVisible({timeout:30000});
 let saved=await snapshot();
 await page.evaluate(()=>{sessionStorage.setItem('concrete-insure-event-test','9');localStorage.setItem('unrelated-setting','preserve');});
 await page.reload();await emptySession(page);await removed(saved);
 assert.equal((await page.request.get(`${server.base}/api/cases/${otherId}`)).status(),200);
 assert.equal(await page.evaluate(()=>localStorage.getItem('unrelated-setting')),'preserve');
 await other.close();
 // Previous-brand cookies and deletion pointers must still remove the old case.
 for(const storageName of ['sessionStorage','localStorage']){
  await upload();saved=await snapshot();
  const owner=(await context.cookies(server.base)).find(cookie=>cookie.name==='concreteinsure_session');
  await context.clearCookies({name:'concreteinsure_session'});
  await context.addCookies([{...owner,name:'insurelens_session'}]);
  await page.evaluate(storageName=>{
   const id=sessionStorage.getItem('concrete-insure-case');sessionStorage.removeItem('concrete-insure-case');
   window[storageName].setItem('insure-lens-case',id);sessionStorage.setItem('insure-lens-event-test','1');
  },storageName);
  await page.reload();await emptySession(page);await removed(saved);
  assert.equal((await context.cookies(server.base)).find(cookie=>cookie.name==='concreteinsure_session').value,owner.value);
 }
 // Successful evidence, source files, OCR drafts and unsent text all disappear.
 await upload();await send('조플루자를 처방받았어요');await expect(page.locator('.drug-selection')).toBeVisible({timeout:30000});
 await page.locator('.drug-selection input[type=checkbox]').first().check();
 await page.getByRole('button',{name:'선택한 제품으로 계속'}).click();await acceptConsent(page);
 await expect(page.locator('.investigation-result')).toBeVisible({timeout:30000});await expect(page.locator('#progress')).toBeHidden();
 await page.locator('.quote-card button').first().click();await expect(page.locator('#highlights polygon').first()).toBeAttached();
 await page.locator('#medicalFile').setInputFiles(pdf);await acceptConsent(page);await expect(page.locator('#ocrPanel')).toBeVisible({timeout:30000});await expect(page.locator('#progress')).toBeHidden();
 await page.locator('#confirmedTerms').fill('oseltamivir');await page.locator('#confirmTerms').click();
 await page.locator('#query').fill('아직 보내지 않은 질문');await page.locator('.drug-section summary').click();await page.locator('#drugName').fill('타미플루');
 saved=await snapshot();
 // Migrate the previous browser version's shared localStorage pointer by deleting it.
 await page.evaluate(()=>{localStorage.setItem('concrete-insure-case',sessionStorage.getItem('concrete-insure-case'));sessionStorage.removeItem('concrete-insure-case');});
 await page.reload();await emptySession(page);await removed(saved);
 // Failed cleanup must retain its deletion pointer and block new work until retry succeeds.
 await upload();saved=await snapshot();let failDelete=true;
 await page.route(`**/api/cases/${saved.id}`,route=>route.request().method()==='DELETE'&&failDelete?route.fulfill({status:503,contentType:'application/json',body:'{"error":"REQUEST_FAILED"}'}):route.continue());
 await page.reload();await expect(page.locator('#retryReset')).toBeVisible();
 for(const id of ['send','policyFile','medicalFile','drugName','clearCase'])await expect(page.locator('#'+id)).toBeDisabled();
 assert.equal(await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case')),saved.id);
 assert.equal((await page.request.get(`${server.base}/api/cases/${saved.id}`)).status(),200);
 failDelete=false;await page.locator('#retryReset').click();await emptySession(page);await removed(saved);
 await page.unroute(`**/api/cases/${saved.id}`);
 // Reload cancels an in-flight provider request and frees the serial job queue.
 await upload();await send('독감 대기');await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:10000});
 saved=await snapshot();await page.reload();await emptySession(page);await removed(saved);
 await upload();await send('독감');await expect(page.locator('.investigation-result')).toBeVisible({timeout:30000});
 // A stale/already-deleted pointer is safe to clean up again.
 saved=await snapshot();await page.request.delete(`${server.base}/api/cases/${saved.id}`,{headers:{'X-Local-Request':'1'}});
 await page.reload();await emptySession(page);await removed(saved);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,resetPendingSelection:true,resetEvidenceAndOcr:true,resetUnsentInputs:true,serverFilesAndRecordsRemoved:true,legacyPointerCleaned:true,previousBrandCleanup:true,unrelatedTabPreserved:true,cleanupFailureRetry:true,runningJobCancelled:true,newSearchCompletes:true,stalePointerHandled:true,browserErrors:errors}));
}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
