import {ready,emptySession} from './browser-session-helper.mjs';
import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startPythonTestServer,python} from './python-test-server.mjs';
import {acceptConsent} from './consent-test-helper.mjs';
const temp=await mkdtemp(path.join(os.tmpdir(),'concreteinsure-consent-'));
const pdf=path.join(temp,'policy.pdf');
execFileSync(python,['-c',"import pymupdf as f,sys; d=f.open();p=d.new_page();p.insert_text((50,100),'독감 인플루엔자',fontname='korea');d.save(sys.argv[1])",pdf]);
const server=await startPythonTestServer(path.join(temp,'data'));
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})}).catch(async error=>{await server.close();await rm(temp,{recursive:true,force:true});throw error;});
const page=await browser.newPage({viewport:{width:1280,height:900}});
page.setDefaultTimeout(15000);
const requests=[],errors=[];
page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/investigations'))requests.push(r.postDataJSON());});
page.on('pageerror',e=>errors.push(e.message));
const consentText='NVIDIA 서비스로 현재·이전 대화의 질문·상황 설명·검색 후보·약관 발췌문을 전송하는 데 동의합니다. 의약품 조회 시 약품명과 품목코드는 식품의약품안전처 API로 전송됩니다.';
async function unchangedJobs(count){const id=await page.evaluate(()=>sessionStorage.getItem('concrete-insure-case'));const response=await page.request.get(`${server.base}/api/cases/${id}`);assert.equal((await response.json()).jobs.filter(j=>j.kind==='investigation').length,count);}
try{
 await page.goto(server.base);await ready(page);await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});
 await expect(page.locator('.settings')).toHaveCount(0);await expect(page.locator('#translation')).toHaveCount(0);
 await page.locator('#query').fill('독감');await page.locator('#send').click();
 await expect(page.locator('#consentDialog')).toBeVisible();await expect(page.locator('#consentDialog label')).toHaveText(consentText);await expect(page.locator('#cloudConsent')).not.toBeChecked();await expect(page.locator('#confirmConsent')).toBeDisabled();
 // A programmatic form submission must not bypass an unchecked consent box.
 await page.locator('#consentForm').evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 await unchangedJobs(0);assert.equal(requests.length,0);await expect(page.locator('.user-message,.investigation-result')).toHaveCount(0);
 if(process.env.SCREENSHOT)await page.screenshot({path:process.env.SCREENSHOT});
 await page.keyboard.press('Escape');await expect(page.locator('#consentDialog')).not.toBeVisible();await expect(page.locator('#query')).toHaveValue('독감');
 await page.locator('#query').fill('독감 진단을 받았습니다.');await page.locator('#send').click();await expect(page.locator('#cloudConsent')).not.toBeChecked();await page.locator('#cloudConsent').check();await page.locator('#cloudConsent').uncheck();await expect(page.locator('#confirmConsent')).toBeDisabled();await page.locator('#cancelConsent').click();await unchangedJobs(0);assert.equal(requests.length,0);
 await page.locator('#query').press('Control+Enter');await expect(page.locator('#consentDialog')).toBeVisible();await page.locator('#cancelConsent').click();assert.equal(requests.length,0);
 await page.locator('#send').click();await acceptConsent(page);await expect(page.locator('.investigation-result')).toHaveCount(1,{timeout:30000});assert.equal(requests.length,1);assert.equal(requests[0].cloudConsent,true);assert.equal(requests[0].translation,undefined);
 await page.locator('#query').fill('인플루엔자');await page.locator('#send').click();await expect(page.locator('#cloudConsent')).not.toBeChecked();await page.locator('#cancelConsent').click();await unchangedJobs(1);assert.equal(requests.length,1);await expect(page.locator('.investigation-result')).toHaveCount(1);
 await page.reload();await emptySession(page);await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});await page.locator('#query').fill('독감');await page.locator('#send').click();await expect(page.locator('#cloudConsent')).not.toBeChecked();await page.locator('#cancelConsent').click();assert.equal(requests.length,1);await page.locator('.drug-section summary').click();await page.locator('#drugName').fill('시험약');await page.locator('#drugForm button').click();await expect(page.locator('#error')).toContainText('식약처 API 키');await expect(page.locator('#error')).toContainText('README');assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,uncheckedBlocked:true,cancelBlocked:true,shortcutBlocked:true,freshConsentEachSearch:true,noRequestOrResultBeforeConsent:true,reloadDoesNotRememberConsent:true,browserErrors:errors}));
}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
