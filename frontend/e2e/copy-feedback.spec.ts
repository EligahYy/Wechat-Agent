import {test,expect} from '@playwright/test';
test('copy feedback is above the modal backdrop and preserves focus',async({page,request,context})=>{
 await context.grantPermissions(['clipboard-read','clipboard-write']);
 await request.post('/api/__test__/reset');await page.goto('/');
 await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 const detail=page.getByRole('dialog');
 const copy=detail.getByRole('button',{name:'复制微信名称',exact:true});
 await copy.click();
 const toast=page.getByRole('status').filter({hasText:'已复制微信名称'});
 await expect(toast).toBeVisible();
 expect(await toast.evaluate(node=>{const box=node.getBoundingClientRect();const top=document.elementFromPoint(box.x+box.width/2,box.y+box.height/2);return top===node||node.contains(top);})).toBe(true);
 await expect(copy).toBeFocused();
 await page.screenshot({path:"../.local/evidence/m2/copy-feedback-fixed.png"});
 expect(await page.evaluate(()=>navigator.clipboard.readText())).toBe('商家甲');
 await toast.click();await expect(toast).toHaveCount(0);
 await expect(detail).toBeVisible();
});
