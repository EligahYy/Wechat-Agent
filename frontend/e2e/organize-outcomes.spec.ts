import {test,expect,type Page} from '@playwright/test';
const issue=(code:string,severity='warning',action='none')=>({code,severity,stage:'metadata',scope:'operation',suggested_action:action});
const record=(extra:Record<string,unknown>={})=>({id:'outcome-case',scope:{account_id:'acct-1',contact_id:'merchant-a'},contact_name_snapshot:'兴🌟',action:'sync_and_organize',state:'succeeded',phase:'completed',source_state:'succeeded',counts:{conversations_total:3,completed_conversations:3,inserted:0},remaining:0,error_code:null,available_actions:[],created_at:'2026-11-16T12:36:00Z',updated_at:'2026-11-16T12:36:10Z',history_complete:false,items:[],report:{version:1,scope_label:'兴🌟',source_outcome:'completed',analysis_outcome:'updated',contacts:[],issues:[issue('source_group_membership_unverified')]},...extra});
async function open(page:Page,r:ReturnType<typeof record>){
 await page.route('**/api/operations?**',route=>route.fulfill({json:{items:[r],total:1,page:1,page_size:20}}));
 await page.route('**/api/operations/outcome-case?**',route=>route.fulfill({json:r}));
 await page.goto('/');await page.getByRole('button',{name:'整理记录',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'整理记录'});await dialog.locator('.history-entry').click();return dialog;
}
test('completed known scope shows customer and warning without a failure label',async({page})=>{
 const d=await open(page,record());await expect(d.locator('.history-entry')).toContainText('兴🌟 · 整理完成');await expect(d.locator('.history-record')).toHaveAttribute('data-tone','success');expect(await d.locator('.history-entry').evaluate(node=>{const c=getComputedStyle(node).backgroundColor.match(/[\d.]+/g)!.map(Number);return c[1]>c[0]&&c[1]>c[2];})).toBe(true);await expect(d.getByText(/消息同步：已完成/)).toBeVisible();await expect(d.getByText('source_group_membership_unverified',{exact:true})).not.toBeVisible();await d.getByText('诊断详情',{exact:true}).click();await expect(d.getByText('source_group_membership_unverified',{exact:true})).toBeVisible();
});
test('model failure keeps source completion and offers settings action',async({page})=>{
 const d=await open(page,record({state:'failed',phase:'analysis',error_code:'model_budget_unverified',report:{version:1,scope_label:'兴🌟',source_outcome:'completed',analysis_outcome:'failed',contacts:[],issues:[issue('model_budget_unverified','blocker','open_model_settings')]}}));await expect(d.getByText(/消息同步：已完成/)).toBeVisible();await expect(d.getByText(/已有资料保留|保留已有资料/)).toBeVisible();await d.getByRole('button',{name:'检查模型设置',exact:true}).click();await expect(page.getByRole('heading',{name:'设置',exact:true})).toBeVisible();
});
test('batch partial outcome names successful and blocked contacts',async({page})=>{
 const d=await open(page,record({scope:{account_id:'acct-1',contact_id:null},contact_name_snapshot:null,state:'failed',report:{version:1,scope_label:'全部范围',source_outcome:'partial',analysis_outcome:'partial',contacts:[{contact_id:'merchant-a',name_snapshot:'兴🌟',analysis_outcome:'not_started',reason:'source_not_complete',issues:[issue('source_timeout','blocker','retry_sync')]},{contact_id:'merchant-b',name_snapshot:'商家乙',analysis_outcome:'updated',reason:null,issues:[]}],issues:[]}}));await expect(d.getByText('兴🌟 · 未执行',{exact:true})).toBeVisible();await expect(d.getByText('商家乙 · 已更新',{exact:true})).toBeVisible();await expect(d.getByRole('button',{name:'重新同步',exact:true})).toBeVisible();
});
test('legacy three of three with failure remains an unknown historical failure',async({page})=>{
 const d=await open(page,record({state:'failed',source_state:'failed',error_code:'source_incomplete',report:null}));await expect(d.locator('.history-entry')).toContainText('来源同步不完整');await expect(d.getByText('此记录未保存具体来源缺口，无法仅凭完成数量判断原因。')).toBeVisible();
});

test('field review remains visible after unchanged input skips the model',async({page})=>{
 const field={...issue('profile_field_invalid'),stage:'publication',scope:'contact',contact_id:'merchant-a',field_path:'goods.volume'};
 const partial={version:1,scope_label:'兴🌟',source_outcome:'completed',analysis_outcome:'partial',contacts:[{contact_id:'merchant-a',name_snapshot:'兴🌟',analysis_outcome:'partial',reason:'analysis_incomplete',issues:[field]}],issues:[]};
 let d=await open(page,record({report:partial}));await expect(d.locator('.history-entry')).toContainText('资料已更新，仍有待核对项');await expect(d.getByText(/待核对：部分字段未通过原文证据校验/)).toBeVisible();
 d=await open(page,record({report:{...partial,analysis_outcome:'unchanged',contacts:[{...partial.contacts[0],analysis_outcome:'unchanged',reason:null}]}}));await expect(d.locator('.history-entry')).toContainText('输入未变化，无需更新');await expect(d.getByText(/待核对：部分字段未通过原文证据校验/)).toBeVisible();
});

test('new customer outcome stays in the list when switching records and reopening history',async({page,request},info)=>{
 await request.post('/api/__test__/reset');
 const older=record({id:'older',report:null,state:'failed',source_state:'failed',error_code:'source_incomplete',created_at:'2026-11-16T11:00:00Z'});
 const latest=record({state:'failed',phase:'analysis',error_code:'context_requires_chunking',report:{version:1,scope_label:'兴🌟',source_outcome:'completed',analysis_outcome:'failed',contacts:[],issues:[{...issue('context_requires_chunking','blocker'),stage:'context'}]}});
 await page.route('**/api/operations?**',route=>route.fulfill({json:{items:[older],total:1,page:1,page_size:20}}));
 await page.route('**/api/operations',route=>route.fulfill({json:latest,status:202}));
 await page.route('**/api/operations/older?**',route=>route.fulfill({json:older}));
 await page.route('**/api/operations/outcome-case?**',route=>route.fulfill({json:latest}));
 await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 const customer=page.getByRole('dialog').first();await customer.getByRole('button',{name:'同步并整理此客户',exact:true}).click();
 await customer.getByRole('button',{name:'查看同步详情',exact:true}).click();
 let history=page.getByRole('dialog',{name:'整理记录'});
 await expect(history.locator('.history-entry')).toHaveCount(2);
 const newest=history.locator('.history-entry').filter({hasText:'消息已同步，整理未完成'});
 await expect(newest).toHaveAttribute('aria-expanded','true');
 await expect(history.locator('.history-record').filter({hasText:'消息已同步，整理未完成'})).toHaveAttribute('data-tone','error');
 expect(await newest.evaluate(node=>{const c=getComputedStyle(node).backgroundColor.match(/[\d.]+/g)!.map(Number);return c[0]>c[1]&&c[0]>c[2];})).toBe(true);
 await expect(history.locator('.operation-facts .info-chip').filter({hasText:'新增 0'})).toBeVisible();
 await expect(history.locator('.operation-outcomes')).toBeVisible();
 await history.locator('.history-entry').filter({hasText:'来源同步不完整'}).click();
 await expect(newest).toBeVisible();await newest.click();
 await expect(history.getByText(/历史超出处理预算/)).toBeVisible();
 await newest.click();await expect(newest).toHaveAttribute('aria-expanded','false');
 await expect(history.getByRole('region',{name:'记录详情'})).toHaveCount(0);
 await newest.click();
 await history.evaluate(async node=>{
   for(let attempt=0;attempt<12;attempt++){
     await new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()));
     const animations=node.getAnimations({subtree:true}).filter(a=>a.effect?.getComputedTiming().iterations!==Infinity);
     if(!animations.length)return;
     await Promise.allSettled(animations.map(a=>a.finished));
   }
 });
 await page.screenshot({path:info.outputPath('unified-history-outcome.png')});
 await history.getByRole('button',{name:'关闭弹窗',exact:true}).click();
 await customer.getByRole('button',{name:'关闭弹窗',exact:true}).click();
 await page.getByRole('button',{name:'整理记录',exact:true}).click();
 history=page.getByRole('dialog',{name:'整理记录'});await expect(history.locator('.history-entry')).toHaveCount(2);
 await history.locator('.history-entry').filter({hasText:'消息已同步，整理未完成'}).click();
 await expect(history.getByText(/历史超出处理预算/)).toBeVisible();
});
