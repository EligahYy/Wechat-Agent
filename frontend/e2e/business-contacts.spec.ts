import {test,expect} from '@playwright/test';
test('business workspace and archived manager preserve manual exclusions',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');
 await expect(page.locator('.brand-mark')).toHaveText('EU');
 await page.getByRole('tab',{name:/业务活跃联系人/}).click();
 await page.getByRole('searchbox').fill('商家甲');
 await expect(page.locator('tbody tr[data-contact]')).toHaveCount(1);
 await page.getByRole('button',{name:'移出业务范围',exact:true}).click();
 await expect(page.locator('tbody tr[data-contact]')).toHaveCount(0);
 await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('button',{name:'管理全部联系人'}).click();
 await page.getByRole('searchbox').fill('商家甲');
 await expect(page.locator('tbody tr[data-contact]')).toHaveCount(1);
 await expect(page.getByText('已手动移出',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'加入业务范围',exact:true}).click();
 await expect(page.getByRole('table',{name:'全部联系人列表'}).getByText('已手动加入',{exact:true})).toBeVisible();
});
test('manager supports bulk changes and scope filtering',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'管理全部联系人'}).click();
 const manager=page.getByRole('region',{name:'联系人管理'});
 await manager.getByRole('searchbox').fill('商家甲');
 await manager.getByRole('checkbox',{name:'选择本页联系人'}).check();
 await manager.getByRole('button',{name:'批量移出业务范围',exact:true}).click();
 await expect(manager.getByText('已手动移出',{exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'业务范围筛选'}).click();await page.getByRole('option',{name:'业务范围内',exact:true}).click();
 await expect(manager.locator('tbody tr')).toHaveCount(0);
 await page.getByRole('combobox',{name:'业务范围筛选'}).click();await page.getByRole('option',{name:'未在业务范围内',exact:true}).click();
 await expect(manager.locator('tbody tr')).toHaveCount(1);
 await page.screenshot({path:'../.local/evidence/m2/task3-manager-light.png',fullPage:true});
 await page.getByRole('button',{name:'切换深色外观'}).click();
 await page.screenshot({path:'../.local/evidence/m2/task3-manager-dark.png',fullPage:true});
});
test('scope actions remain on one line at desktop width',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('tab',{name:/业务活跃联系人/}).click();
 const action=page.locator('tbody .cell-actions').first().getByRole('button',{name:'移出业务范围',exact:true});
 await expect(action).toBeVisible();
 expect(await action.evaluate(node=>node.getBoundingClientRect().height)).toBeLessThan(40);
});
test('scope conflict stays visible and clears stale selections',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('tab',{name:/业务活跃联系人/}).click();
 await page.getByRole('searchbox').fill('商家甲');await page.getByRole('checkbox',{name:'选择本页联系人'}).check();
 await page.route('**/api/contacts/scope',route=>route.fulfill({status:409,json:{code:'scope_version_conflict',details:{updated:[],failed:[{key:{account_id:'acct-1',contact_id:'merchant-a'},current_version:1}]}}}));
 await page.getByRole('button',{name:'批量移出业务范围',exact:true}).click();
 await page.waitForResponse(response=>response.url().includes('/api/contacts?'));
 await expect(page.getByRole('alert')).toContainText('信息已变化');
 await expect(page.getByRole('checkbox',{name:'选择本页联系人'})).not.toBeChecked();
});
test('role changes in manager invalidate workspace immediately',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('tab',{name:/业务活跃联系人/}).click();
 await page.getByRole('searchbox').fill('商家甲');
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'管理全部联系人'}).click();
 await page.getByRole('searchbox').fill('商家甲');await expect(page.getByRole('table').locator('tbody tr')).toHaveCount(1);await page.getByRole('button',{name:'修改身份',exact:true}).click();await page.getByRole('menuitemradio',{name:'服务商'}).click();
 await page.getByRole('button',{name:'工作台',exact:true}).click();
 await expect(page.getByRole('table').getByText('服务商',{exact:true})).toBeVisible();
});
