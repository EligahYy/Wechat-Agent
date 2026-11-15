import {test,expect} from '@playwright/test';

test('contact settings card aligns with other settings and supports keyboard entry and return',async({page,request})=>{
  await request.post('/api/__test__/reset');
  await page.goto('/');
  await page.getByRole('button',{name:'设置',exact:true}).click();
  const heading=page.getByRole('heading',{name:'联系人管理',exact:true});
  const other=page.getByRole('heading',{name:'本机数据与模型',exact:true});
  const card=heading.locator('..');
  const titleBox=await heading.boundingBox(),otherBox=await other.boundingBox();
  expect(titleBox).not.toBeNull();expect(otherBox).not.toBeNull();
  expect(Math.abs(titleBox!.x-otherBox!.x)).toBeLessThan(2);
  const entry=page.getByRole('button',{name:'管理全部联系人',exact:true});
  await entry.focus();await page.keyboard.press('Enter');
  await expect(page.getByRole('region',{name:'联系人管理'})).toBeVisible();
  await page.getByRole('button',{name:'返回设置',exact:true}).click();
  await expect(heading).toBeVisible();await expect(entry).toBeVisible();
  for(const width of [1180,1920]){
    await page.setViewportSize({width,height:1000});
    await expect(card).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  await page.screenshot({path:'../.local/evidence/m2/settings-contacts-fixed-light.png',fullPage:true});
  await page.getByRole('button',{name:'切换深色外观'}).click();
  await page.screenshot({path:'../.local/evidence/m2/settings-contacts-fixed-dark.png',fullPage:true});
});
