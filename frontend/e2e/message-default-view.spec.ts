import {test,expect} from '@playwright/test';
test('message tab opens latest all-source details directly with a stable animated envelope',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await page.waitForTimeout(350);const overview=await dialog.boundingBox();
 const placeholder=dialog.locator('.profile-empty');
 const spacing=await placeholder.evaluate(node=>{const [icon,title,note]=Array.from(node.children).map(child=>child.getBoundingClientRect());const box=node.getBoundingClientRect();return {iconGap:title.top-icon.bottom,noteGap:note.top-title.bottom,center:Math.abs((icon.top+note.bottom)/2-(box.top+box.bottom)/2)};});
 expect(spacing.iconGap).toBeLessThan(20);expect(spacing.noteGap).toBeLessThan(20);expect(spacing.center).toBeLessThan(5);

 await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await expect(dialog.getByRole('region',{name:'当天消息详情'})).toBeVisible();
 await expect(dialog.locator('[data-message]')).toHaveCount(4);await expect(dialog.getByRole('combobox',{name:'消息来源'})).toHaveText('全部来源');
 await page.waitForTimeout(350);const messages=await dialog.boundingBox();expect(Math.abs(messages!.width-overview!.width)).toBeLessThan(2);expect(Math.abs(messages!.height-overview!.height)).toBeLessThan(20);
 await expect(dialog.locator('.message-browser')).toHaveCSS('animation-name','page-in');
});
