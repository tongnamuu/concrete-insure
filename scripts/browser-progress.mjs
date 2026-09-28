import {ready} from './browser-session-helper.mjs';
import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startPythonTestServer,python} from './python-test-server.mjs';
import {acceptConsent} from './consent-test-helper.mjs';
const temp=await mkdtemp(path.join(os.tmpdir(),'concreteinsure-progress-'));
const pdf=path.join(temp,'policy.pdf');
execFileSync(python,['-c',"import pymupdf as f,sys; d=f.open();p=d.new_page();p.insert_text((50,100),'독감 인플루엔자',fontname='korea');d.save(sys.argv[1])",pdf]);
const server=await startPythonTestServer(path.join(temp,'data'),'tests.browser_server:create_slow_test_app');
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})}).catch(async error=>{await server.close();await rm(temp,{recursive:true,force:true});throw error;});
const page=await browser.newPage();const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(server.base);await ready(page);await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});
 await page.locator('#query').fill('독감');await page.locator('#send').click();await acceptConsent(page);
 await expect(page.locator('#progressText')).toHaveText('검색 1단계',{timeout:12000});
 // Record visible text throughout the wait and the following search.
 await page.locator('#progressText').evaluate(node=>{window.searchProgress=[];new MutationObserver(()=>window.searchProgress.push(node.textContent)).observe(node,{childList:true,characterData:true,subtree:true});});
 await expect.poll(()=>page.evaluate(()=>window.searchProgress.includes('검색 1단계')),{timeout:12000}).toBe(true);
 await expect(page.locator('.investigation-result')).toHaveCount(0);
 await page.locator('#cancelJob').click();await expect(page.locator('#progress')).not.toBeVisible({timeout:10000});
 const caseId=await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case'));
 const res=await page.request.get(`${server.base}/api/cases/${caseId}`);const job=(await res.json()).jobs.find(j=>j.kind==='investigation');
 assert.equal(job.state,'cancelled');await expect(page.locator('.investigation-result')).toHaveCount(0);
 await page.locator('#query').fill('독감');await page.locator('#send').click();await acceptConsent(page);
 await expect(page.locator('.investigation-result')).toHaveCount(1,{timeout:20000});await expect(page.locator('#progress')).not.toBeVisible();
 const messages=await page.evaluate(()=>window.searchProgress);assert(messages.includes('검색 2단계'));assert(!messages.some(text=>text.includes('NVIDIA')));
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,waitProgressVisible:true,cancellationWithoutResult:true,nextSearchCompletes:true,browserErrors:errors}));
}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
