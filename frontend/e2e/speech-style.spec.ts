import {test,expect} from '@playwright/test';
test('compact speech navigator stays top right with icon buttons and soft selection',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).waitFor({state:'visible'});
 const nav=dialog.locator('.speech-navigation');await expect(dialog.locator('.is-current-speech')).toBeVisible();
 await dialog.locator('.timeline-result-enter').evaluate(async node=>{await Promise.allSettled(node.getAnimations().map(animation=>animation.finished));});
 await dialog.locator('.timeline-scroll').evaluate(node=>node.scrollTo({top:0,behavior:'instant'}));
 const floating=await nav.boundingBox(),firstMessage=await dialog.locator('[data-message]').first().boundingBox();
 expect(floating!.y).toBeGreaterThanOrEqual(firstMessage!.y-2);
 expect(floating!.y).toBeLessThan(firstMessage!.y+20);
 await expect(dialog.locator('.timeline-items')).toHaveCSS('padding-top','0px');

 expect((await nav.boundingBox())!.width).toBeLessThan(240);
 expect(await nav.getByRole('button',{name:'上一条',exact:true}).innerText()).toBe('');
 await expect(dialog.locator('.is-current-speech')).toHaveCSS('outline-style','none');
 await nav.getByRole('button',{name:'上一条',exact:true}).click();
 await expect(nav.getByRole('button',{name:'下一条',exact:true})).toBeEnabled();
 for(const theme of ['light','dark']){
  await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
  await page.waitForTimeout(200);
  await dialog.locator('.timeline-scroll').evaluate(node=>node.scrollTo({top:node.scrollHeight,behavior:'instant'}));
  await expect(nav).toBeInViewport();
  const box=await nav.boundingBox(),body=await dialog.locator('.timeline-scroll').boundingBox();
  expect(body!.x+body!.width-box!.x-box!.width).toBeLessThan(60);
  await page.screenshot({path:`../.local/evidence/m2/speech-style-${theme}.png`});
 }
});
