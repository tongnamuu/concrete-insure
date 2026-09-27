import assert from 'node:assert/strict';
import {chromium,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';import {mkdtemp,rm} from 'node:fs/promises';import path from 'node:path';import os from 'node:os';
import {startPythonTestServer,python} from './python-test-server.mjs';
const temp=await mkdtemp(path.join(os.tmpdir(),'insurelens-coverage-ui-'));
const pdf=path.join(temp,'test-policy.pdf');execFileSync(python,['-c',`import pymupdf as f,sys
d=f.open();p=d.new_page()
lines=['6-36 독감(인플루엔자)항바이러스제치료 특별약관','제1조 (보험금의 지급사유)','보험기간 중 인플루엔자 진단을 받고 치료를 목적으로','항바이러스제를 처방받은 경우 연간 1회 보험금을 지급합니다.','  ','제2조 (독감(인플루엔자)의 정의 및 진단확정)','진단 당시 식품의약품안전처에서 허가된 치료제를 말합니다.']
for i,t in enumerate(lines):p.insert_text((40,60+45*i),t,fontname='korea')
p=d.new_page()
lines=['성분명 안내: 발록사비르(baloxavir)','신규 허가 또는 허가 취소시 변경될 수 있습니다.','제3조 (보험금을 지급하지 않는 사유)','보통약관 제8조 제1항을 따릅니다.','제4조 (보험금의 청구)','처방전과 청구서를 제출합니다.','6-37 다른 질병 특별약관','제1조 (보험금의 지급사유)','다른 질병은 다른 기준으로 지급합니다.']
for i,t in enumerate(lines):p.insert_text((40,60+45*i),t,fontname='korea')
d.save(sys.argv[1])`,pdf]);
const server=await startPythonTestServer(path.join(temp,'test-data'));const base=server.base;
const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})}).catch(async error=>{await server.close();await rm(temp,{recursive:true,force:true});throw error;});
const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(base);await page.locator('#policyFile').setInputFiles(pdf);await expect(page.locator('#documentName')).toHaveText('test-policy.pdf',{timeout:30000});
 await page.locator('#description').fill('조플루자를 처방받았습니다.');await page.locator('#searchDescription').click();
 await expect(page.locator('.coverage-status')).toHaveText('약관에 관련 보장 항목이 명시되어 있습니다.',{timeout:60000});
 await expect(page.locator('.coverage-link')).toContainText('성분 근거를 통한 간접 연결');await expect(page.locator('.coverage-link')).toContainText('조플루자 → 발록사비르');await expect(page.locator('.coverage-caution')).toContainText('실제 보장은');
 await expect(page.locator('.coverage-panel')).not.toContainText('다른 질병');
 const clauses=page.locator('.coverage-panel .clause-group');assert.equal(await clauses.count(),4);
 const blocks=await page.locator('.quote-card blockquote').allTextContents();assert(blocks.length>0);assert(blocks.every(t=>/[^\s\p{C}]/u.test(t)));
 const definition=page.locator('.clause-group[data-kind="definition"]');await definition.locator('summary').click();await definition.locator('.quote-card').filter({hasText:'발록사비르'}).locator('button').click();await expect(page.locator('#pageNumber')).toHaveValue('2');await expect(page.locator('#highlights polygon').first()).toBeAttached();
 const got=page.waitForEvent('download');await page.locator('#download').click();const download=await got;await download.saveAs(path.join(temp,'marked.pdf'));
 execFileSync(python,['-c',"import pymupdf as f,sys;d=f.open(sys.argv[1]);assert sum(len(list(p.annots() or [])) for p in d)>0;assert '발록사비르' in ''.join(p.get_text() for p in d)",path.join(temp,'marked.pdf')]);
 // A compact screenshot of the decision scope and source connection; no personal data.
 await page.locator('.clause-group[data-kind="payment"] summary').click();await definition.locator('summary').click();if(process.env.SCREENSHOT)await page.locator('.coverage-panel').screenshot({path:process.env.SCREENSHOT});
 await page.locator('#clearResults').click();await expect(page.locator('.coverage-panel')).toHaveCount(0);await expect(page.locator('#highlights polygon')).toHaveCount(0);await expect(page.locator('#download')).toBeDisabled();await page.reload();await expect(page.locator('.textLayer')).not.toBeEmpty({timeout:30000});await expect(page.locator('.coverage-panel')).toHaveCount(0);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,orchestrator:process.env.TEST_AGENT_RUNNER||'auto',policyBenefit:true,ingredientLink:true,allFourClauses:true,noBlankCards:true,nextRiderExcluded:true,highlight:true,download:true,clearAndReload:true,browserErrors:errors}));
}catch(e){console.error(JSON.stringify({error:e.message,uiError:await page.locator('#error').textContent()}));process.exitCode=1;}finally{await browser.close();await server.close();await rm(temp,{recursive:true,force:true});}
