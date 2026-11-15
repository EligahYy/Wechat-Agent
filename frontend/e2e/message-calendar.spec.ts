import {test,expect} from '@playwright/test';
test('calendar opens day details, preserves all speakers and returns to latest',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();
 await expect(dialog.getByRole('region',{name:'消息日历'})).toBeVisible();
 await expect(dialog.getByRole('searchbox',{name:'搜索沟通原文'})).toHaveCount(0);
 await dialog.getByRole('button',{name:'回到最新',exact:true}).click();
 await expect(dialog.getByRole('region',{name:'当天消息详情'})).toBeVisible();
 await expect(dialog.locator('[data-message]')).toHaveCount(4);
 await expect(dialog.locator('[data-message]:not(.is-contact)')).not.toHaveCount(0);
 await expect(dialog.getByRole('button',{name:/加载.*原文/})).toHaveCount(0);
 await expect(dialog.getByRole('button',{name:'2026-11-11，4条消息'})).toHaveAttribute('aria-pressed','true');
 await page.screenshot({path:'../.local/evidence/m2/calendar-messages-light.png'});
});
test('day selection, empty day, month browsing and narrow layout preserve context',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();
 await dialog.getByRole('button',{name:'2026-11-11，4条消息'}).click();
 await expect(dialog.locator('[data-message]')).toHaveCount(4);
 await dialog.getByRole('button',{name:'2026-11-12，暂无消息'}).click();
 await expect(dialog.getByText('当天暂无已同步消息',{exact:true})).toBeVisible();
 await dialog.getByRole('region',{name:'当天消息详情'}).getByRole('button',{name:'回到最新',exact:true}).click();
 await expect(dialog.locator('[data-message]')).toHaveCount(4);
 await dialog.getByRole('button',{name:'上个月',exact:true}).click();
 await expect(dialog.getByRole('region',{name:'当天消息详情'}).getByRole('heading')).toHaveText('2026 / 11 / 11');
 await page.setViewportSize({width:900,height:960});
 await expect(dialog.getByRole('region',{name:'消息日历'})).not.toBeVisible();
 await dialog.getByRole('button',{name:'选择日期',exact:true}).click();
 await expect(dialog.getByRole('region',{name:'消息日历'})).toBeVisible();
 await expect(dialog.getByRole('button',{name:'回到最新',exact:true})).toBeVisible();
});
test('keyboard crosses months and focuses the requested day after metadata loads',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();
 await expect(dialog.getByRole('button',{name:'2026-11-01，暂无消息'})).toBeEnabled();
 await page.route('**/message-calendar?*',async route=>{if(new URL(route.request().url()).searchParams.get('month')==='2026-10')await new Promise(resolve=>setTimeout(resolve,300));await route.continue();});
 await dialog.getByRole('button',{name:'2026-11-01，暂无消息'}).focus();await page.keyboard.press('ArrowLeft');
 await expect(dialog.getByRole('button',{name:'2026-10-31，暂无消息'})).toBeEnabled();
 await expect(dialog.getByRole('button',{name:'2026-10-31，暂无消息'})).toBeFocused();
});
test('failed day switch never displays old messages under the new date',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('button',{name:'回到最新',exact:true}).click();await expect(dialog.locator('[data-message]')).toHaveCount(4);
 await page.route('**/messages?*',route=>new URL(route.request().url()).searchParams.get('day')==='2026-11-12'?route.fulfill({status:503,json:{code:'database_unavailable'}}):route.continue());
 await dialog.getByRole('button',{name:'2026-11-12，暂无消息'}).click();await expect(dialog.getByRole('alert')).toBeVisible();await expect(dialog.locator('[data-message]')).toHaveCount(0);
});
test('edge text clicks do not page; wheel loads earlier while keeping the visible anchor',async({page,request})=>{
 await request.post('/api/__test__/reset');
 const mapping=Object.fromEntries(['conversation_id','sender_id','sent_at','message_id','body'].map(key=>[key,key]));
 const rows=Array.from({length:60},(_,i)=>({conversation_id:'group-1',sender_id:'merchant-a',sent_at:new Date(Date.UTC(2026,10,14,0,i)).toISOString(),message_id:`edge-${i}`,body:`滚动边缘${i}`}));
 const preview=await(await request.post('/api/imports',{data:{mode:'preview',account_id:'acct-1',namespace:'edges',format:'json',mapping,content:JSON.stringify(rows)}})).json();await request.post('/api/imports',{data:{mode:'commit',account_id:'acct-1',preview_id:preview.preview_id}});
 await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();const dialog=page.getByRole('dialog');await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('button',{name:'回到最新',exact:true}).click();await expect(dialog.locator('[data-message]')).toHaveCount(26);
 const scroll=dialog.locator('.timeline-scroll');await scroll.evaluate(node=>node.scrollTo({top:0,behavior:'instant'}));
 let calls=0;page.on('request',req=>{if(new URL(req.url()).searchParams.has('before_cursor'))calls++;});
 await dialog.locator('.original-body').first().click();await page.waitForTimeout(250);expect(calls).toBe(0);
 const anchor=dialog.locator('[data-message]').first();const id=await anchor.getAttribute('data-message'),top=(await anchor.boundingBox())!.y;
 await scroll.hover();await page.mouse.wheel(0,-1000);await expect(dialog.locator('[data-message]')).toHaveCount(60);
 expect(Math.abs((await dialog.locator(`[data-message="${id}"]`).boundingBox())!.y-top)).toBeLessThan(5);
});
