import {expect} from '@playwright/test';
export async function ready(page){
 await expect(page.locator('#availability')).toHaveText('검색 준비 완료',{timeout:30000});
 await expect(page.locator('#policyFile')).toBeEnabled();
}
export async function emptySession(page){
 await ready(page);
 await expect(page.locator('#documentName')).toHaveText('약관 원문');
 await expect(page.locator('#pdfEmpty')).toBeVisible();
 for(const id of ['pdfPage','progress','error','retryReset'])await expect(page.locator('#'+id)).toBeHidden();
 await expect(page.locator('.user-message,.assistant-message,.quote-card,#highlights polygon')).toHaveCount(0);
 for(const id of ['query','drugName','policyFile'])await expect(page.locator('#'+id)).toHaveValue('');
 await expect(page.locator('#download')).toBeDisabled();
 await expect(page.locator('#pageNumber')).toHaveValue('1');
 await expect(page.locator('#zoomValue')).toHaveText('100%');
 await expect(page.locator('#cloudConsent')).not.toBeChecked();
 await expect(page.locator('#drugResults')).toBeEmpty();
}
