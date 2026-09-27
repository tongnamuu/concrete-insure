import {expect} from '@playwright/test';
export async function acceptConsent(page){
 await expect(page.locator('#consentDialog')).toBeVisible();
 await expect(page.locator('#cloudConsent')).not.toBeChecked();
 await expect(page.locator('#confirmConsent')).toBeDisabled();
 await page.locator('#cloudConsent').check();
 await page.locator('#confirmConsent').click();
 await expect(page.locator('#consentDialog')).not.toBeVisible();
}
