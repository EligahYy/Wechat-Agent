import {test,expect} from '@playwright/test';

const records=Array.from({length:18},(_,index)=>({id:`history-${index}`,scope:{account_id:'acct-1',contact_id:null},action:'sync_and_organize',state:'failed',source_state:'failed',phase:'source',counts:{conversations_total:index+1,completed_conversations:0},remaining:1,error_code:'source_incomplete',available_actions:[],updated_at:new Date(Date.UTC(2026,10,13,12,index)).toISOString(),history_complete:false,items:[{phase:'source',state:'failed',error_code:'source_incomplete',gaps:['source_timeout']}]}));

test.beforeEach(async({page,request})=>{
 await request.post('/api/__test__/reset');
 await page.route('**/api/operations?**',route=>route.fulfill({json:{items:records,total:18}}));
 await page.route('**/api/operations/history-*?**',route=>{const id=new URL(route.request().url()).pathname.split('/').at(-1);return route.fulfill({json:records.find(record=>record.id===id)});});
 await page.goto('/');await page.getByRole('button',{name:'整理记录',exact:true}).click();
});

test('a record expands beside its clicked row even after scrolling down',async({page})=>{
 const dialog=page.getByRole('dialog',{name:'整理记录'}),row=dialog.locator('.history-entry').nth(15);
 await row.click();
 await expect(row).toHaveAttribute('aria-expanded','true');
 const detail=dialog.getByRole('region',{name:'记录详情'});
 await expect(detail.getByText('目标会话 16')).toBeVisible();
 const buttonBox=await row.boundingBox(),detailBox=await detail.boundingBox();
 expect(detailBox!.y).toBeGreaterThan(buttonBox!.y);
 expect(detailBox!.y-buttonBox!.y-buttonBox!.height).toBeLessThan(40);
 await row.click();await expect(detail).toHaveCount(0);
});

test('a late response cannot replace the newly selected record',async({page})=>{
 let release!:()=>void;
 const gate=new Promise<void>(resolve=>{release=resolve;});
 let started!:()=>void;const requested=new Promise<void>(resolve=>{started=resolve;});
 await page.route('**/api/operations/history-0?**',async route=>{started();await gate;await route.fulfill({json:records[0]}).catch(()=>{});});
 const dialog=page.getByRole('dialog',{name:'整理记录'});
 await dialog.locator('.history-entry').nth(0).click();await requested;
 const aborted=page.waitForEvent('requestfailed',request=>request.url().includes('/operations/history-0?'));
 await dialog.locator('.history-entry').nth(1).click();await aborted;
 await expect(dialog.getByRole('region',{name:'记录详情'}).getByText('目标会话 2')).toBeVisible();
 release();
 await expect(dialog.locator('.history-entry').nth(1)).toHaveAttribute('aria-expanded','true');
 await expect(dialog.getByRole('region',{name:'记录详情'}).getByText('目标会话 2')).toBeVisible();
});

test('failed detail reads can retry inside the selected row',async({page})=>{
 let attempts=0;
 await page.route('**/api/operations/history-2?**',route=>++attempts===1?route.fulfill({status:503,json:{code:'unavailable'}}):route.fulfill({json:records[2]}));
 const dialog=page.getByRole('dialog',{name:'整理记录'});await dialog.locator('.history-entry').nth(2).click();
 const detail=dialog.getByRole('region',{name:'记录详情'});
 await expect(detail.getByRole('alert')).toBeVisible();await detail.getByRole('button',{name:'重试'}).click();
 await expect(detail.getByText('目标会话 3')).toBeVisible();
});

test('customer shortcut reveals its record after the history dialog was scrolled',async({page})=>{
 const scoped=records.map((record,index)=>index===0?{...record,scope:{account_id:'acct-1',contact_id:'merchant-a'}}:record);
 await page.route('**/api/operations?**',route=>route.fulfill({json:{items:scoped,total:18}}));
 await page.reload();await page.getByRole('button',{name:'整理记录',exact:true}).click();
 const history=page.getByRole('dialog',{name:'整理记录'});
 await history.locator('.history-entry').last().scrollIntoViewIfNeeded();
 await history.getByRole('button',{name:'关闭弹窗'}).click();await expect(history).not.toBeVisible();
 await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 await page.getByRole('button',{name:'查看同步详情',exact:true}).click();
 await expect(history.getByRole('region',{name:'记录详情'}).getByText('目标会话 1')).toBeInViewport();
});
