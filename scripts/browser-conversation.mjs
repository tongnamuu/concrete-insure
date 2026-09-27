import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {startPythonTestServer,python} from './python-test-server.mjs';
import {acceptConsent} from './consent-test-helper.mjs';
const temp=await mkdtemp(path.join(os.tmpdir(),'insurelens-conversation-'));
const pdf=path.join(temp,'policy.pdf');
execFileSync(python,['-c',"import pymupdf as f,sys; d=f.open();p=d.new_page();p.insert_text((50,100),'테스트 약관: 독감 항바이러스제 치료. 제외사항은 별도 확인.',fontname='korea');d.save(sys.argv[1])",pdf]);
const server=await startPythonTestServer(path.join(temp,'data'),'tests.browser_server:create_conversation_test_app');
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})}).catch(async error=>{await server.close();await rm(temp,{recursive:true,force:true});throw error;});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/investigations'))requests.push(r.postDataJSON());});
async function send(text,count){await page.locator('#query').fill(text);await page.locator('#send').click();await acceptConsent(page);await expect(page.locator('.investigation-result')).toHaveCount(count,{timeout:30000});await expect(page.locator('#progress')).toBeHidden();}
try{
 await page.goto(server.base);await expect(page.locator('#description')).toHaveCount(0);await expect(page.locator('#query')).toHaveAttribute('maxlength','4000');
 await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('policy.pdf',{timeout:30000});
 await send('독감 관련 내용을 찾아줘',1);await send('그 경우 제외사항은?',2);
 assert.equal(requests[0].conversationId,requests[1].conversationId);assert(!('conversation' in requests[1]));assert(!('description' in requests[1]));
 await expect(page.locator('.user-message')).toHaveCount(2);await expect(page.locator('.investigation-result').last()).toContainText('독감');
 await expect(page.locator('.earlier-turn')).toHaveCount(1);
 await page.locator('.investigation-result').last().locator('.quote-card button').first().click();await expect(page.locator('#highlights polygon').first()).toBeAttached();
 await page.reload();await expect(page.locator('.user-message')).toHaveCount(2,{timeout:30000});await expect(page.locator('.investigation-result')).toHaveCount(2);
 assert((await page.locator('#queryForm').boundingBox()).y+(await page.locator('#queryForm').boundingBox()).height<=1001);
 if(process.env.SCREENSHOT)await page.screenshot({path:process.env.SCREENSHOT,fullPage:true});
 await page.locator('#query').fill('그 경우 제외사항은?');await page.locator('#send').click();await expect(page.locator('#cloudConsent')).not.toBeChecked();await page.locator('#cancelConsent').click();assert.equal(requests.length,2);
 await page.locator('#clearResults').click();await expect(page.locator('.user-message,.investigation-result')).toHaveCount(0);await expect(page.locator('#highlights polygon')).toHaveCount(0);await expect(page.locator('#download')).toBeDisabled();
 await page.reload();await expect(page.locator('#documentName')).toHaveText('policy.pdf');await expect(page.locator('.user-message,.investigation-result')).toHaveCount(0);
 await page.locator('#query').fill('그 경우 제외사항은?');await page.locator('#send').click();await acceptConsent(page);await expect(page.locator('.assistant-message')).toContainText('검색할 구체적인 정보를 찾지 못했습니다.',{timeout:30000});await expect(page.locator('.investigation-result')).toHaveCount(0);
 assert.notEqual(requests[0].conversationId,requests[2].conversationId);
 await page.locator('.assistant-message button').click();await expect(page.locator('#query')).toHaveValue('그 경우 제외사항은?');
 await send('독감',1);
 await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('.user-message,.investigation-result,.assistant-message')).toHaveCount(0,{timeout:30000});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,singleInput:true,followUpWithSource:true,reloadRestoresConversation:true,newConversationClearsContext:true,consentEachTurn:true,failureCanBeReentered:true,documentReplacementClearsContext:true,browserErrors:errors}));
}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
