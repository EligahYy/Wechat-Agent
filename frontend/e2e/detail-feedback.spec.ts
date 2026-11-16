import { test,expect,type Locator } from '@playwright/test';
async function settleAnimations(locator:Locator) {
  await locator.evaluate(async node=>{
    for(let attempt=0;attempt<12;attempt++){
      await new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()));
      const animations=node.getAnimations({subtree:true}).filter(animation=>animation.effect?.getComputedTiming().iterations!==Infinity);
      if(!animations.length)return;
      // ResizeObserver may retarget a transition while data arrives; its old
      // finished promise rejects on cancellation, then the replacement settles.
      await Promise.allSettled(animations.map(animation=>animation.finished));
    }
    throw Error('Dialog animation did not settle');
  });
}
test.beforeEach(async({page,request})=>{await request.post('/api/__test__/reset');await page.goto('/');});
test('customer sees scoped progress and result without closing or scrolling up',async({page},info)=>{
  let finished=false;
  const submitted=page.waitForRequest(request=>request.method()==='POST'&&request.url().endsWith('/api/operations'));
  await page.route('**/api/operations/*?**',async route=>{
    const response=await route.fetch();const operation=await response.json();
    await route.fulfill({json:{...operation,report:null,state:finished?'failed':'running',phase:finished?'completed':'source',
      source_state:finished?'failed':'running',error_code:finished?'capability_not_ready':null,available_actions:finished?[]:['stop'],
      counts:{...operation.counts,conversations_total:3,completed_conversations:finished?3:1,pages_processed:finished?4:1,inserted:2}}});
  });
  await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
  const detail=page.getByRole('dialog');
  await detail.getByRole('button',{name:'同步并整理此客户',exact:true}).click();
  expect((await submitted).postDataJSON()).toMatchObject({action:'sync_and_organize',scope:{account_id:'acct-1',contact_id:'merchant-a'}});
  const progress=detail.getByRole('region',{name:'当前客户同步状态'});
  await expect(progress.getByText('正在同步微信原文',{exact:true})).toBeVisible();
  await expect(progress.getByRole('progressbar')).toHaveAttribute('value','1');
  await expect(detail.getByRole('button',{name:'同步中…',exact:true})).toBeDisabled();
  await detail.locator('.dialog-body').evaluate(node=>node.scrollTop=node.scrollHeight);
  await expect(progress).toBeInViewport();
  await page.screenshot({path:info.outputPath('customer-progress.png')});
  finished=true;
  await expect(progress.getByText('原文已同步，档案整理尚未接入',{exact:true})).toBeVisible();
  await expect(progress.getByText(/已完成 3 \/ 3 个会话/)).toBeVisible();
  await detail.getByRole('button',{name:'关闭弹窗',exact:true}).click();
  await page.getByRole('button',{name:'查看 商家乙',exact:true}).click();
  await expect(page.getByRole('region',{name:'当前客户同步状态'})).toHaveCount(0);
});
test('customer tabs keep a stable envelope and animate content and search',async({page,request})=>{
  const row={conversation_id:'group-1',sender_id:'merchant-a',sent_at:'2026-11-13T08:00:00+08:00',body:'动画原文'};
  const preview=await(await request.post('/api/imports',{data:{mode:'preview',account_id:'acct-1',format:'json',namespace:'animation',
    mapping:Object.fromEntries(['conversation_id','sender_id','sent_at','message_id','body'].map(key=>[key,key])),
    content:JSON.stringify(Array.from({length:30},(_,index)=>({...row,message_id:String(index)})))}})).json();
  await request.post('/api/imports',{data:{mode:'commit',account_id:'acct-1',preview_id:preview.preview_id}});
  await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await settleAnimations(dialog);
  const initial=(await dialog.boundingBox())!.height;
  await dialog.evaluate(node=>{const samples:number[]=[];(window as any).__heights=samples;const start=performance.now();
    const sample=()=>{samples.push(node.getBoundingClientRect().height);if(performance.now()-start<1100)requestAnimationFrame(sample);else (window as any).__heightDone=true;};requestAnimationFrame(sample);});
  await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).waitFor({state:'visible'});
  await expect(dialog.getByText('30 条原文',{exact:true})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>(window as any).__heightDone)).toBe(true);
  const end=(await dialog.boundingBox())!.height;
  const samples:number[]=await page.evaluate(()=>(window as any).__heights);
  expect(Math.abs(end-initial)).toBeLessThan(20);
  await expect(dialog.locator(".message-browser")).toHaveCSS("animation-name","page-in");
  await dialog.evaluate(node=>{(window as any).__heightDone=false;const samples:number[]=[];(window as any).__heights=samples;const start=performance.now();
    const sample=()=>{samples.push(node.getBoundingClientRect().height);if(performance.now()-start<700)requestAnimationFrame(sample);else (window as any).__heightDone=true;};requestAnimationFrame(sample);});
  await dialog.getByRole('tab',{name:'资料概览',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>(window as any).__heightDone)).toBe(true);
  const shrunk=(await dialog.boundingBox())!.height;
  const reverse:number[]=await page.evaluate(()=>(window as any).__heights);
  expect(Math.abs(shrunk-end)).toBeLessThan(20);
  await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).waitFor({state:'visible'});
  await expect(dialog.locator('[data-message]')).toHaveCount(26);
  await page.route('**/api/contacts/*/messages?**',async route=>{
    if(new URL(route.request().url()).searchParams.get('q'))await new Promise(resolve=>setTimeout(resolve,350));
    await route.continue();
  });
  await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).fill('不会存在的原文');
  await expect(dialog.locator('[data-message]')).toHaveCount(0);
  await expect(dialog.getByText('没有匹配的原文')).toBeVisible();
  await expect(dialog.locator('.timeline-result-enter')).toHaveCSS('animation-name','timeline-result-in');
  await page.emulateMedia({reducedMotion:'reduce'});
  await dialog.getByRole('button',{name:'清空原文搜索'}).click();
  await expect(dialog.locator('[data-message]')).toHaveCount(26);
  expect(await dialog.locator('.dialog-body').evaluate(node=>parseFloat(getComputedStyle(node).transitionDuration))).toBeLessThan(.01);
});
test('submission errors are shown in this customer and retry can complete the source phase',async({page})=>{
  await page.route('**/api/operations',route=>route.fulfill({status:503,json:{code:'database_unavailable',message:'',details:{}}}));
  await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('button',{name:'同步并整理此客户',exact:true}).click();
  const status=dialog.getByRole('region',{name:'当前客户同步状态'});
  await expect(status.getByText('同步请求未提交',{exact:true})).toBeVisible();
  await expect(status.getByRole('alert')).toBeVisible();
  await page.unroute('**/api/operations');
  await dialog.getByRole('button',{name:'同步并整理此客户',exact:true}).click();
  await expect(status.getByText('消息已同步，整理未完成',{exact:true})).toBeVisible();
  await expect(status.getByRole('alert')).toHaveCount(0);
});
test('an open source menu follows the dialog while search changes its height',async({page})=>{
  await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('tab',{name:'沟通原文',exact:true}).click();await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).waitFor({state:'visible'});
  await expect(dialog.locator('[data-message]')).toHaveCount(4);
  await settleAnimations(dialog.locator('.dialog-body'));
  await page.route('**/api/contacts/*/messages?**',async route=>{await new Promise(resolve=>setTimeout(resolve,400));await route.continue();});
  await dialog.getByRole('searchbox',{name:'搜索沟通原文'}).fill('未出现过的内容');
  await dialog.getByRole('combobox',{name:'消息来源'}).click();
  await expect(dialog.getByText('没有匹配的原文')).toBeVisible();
  await settleAnimations(dialog.locator('.dialog-body'));
  await expect.poll(async()=>{
    const trigger=await dialog.getByRole('combobox',{name:'消息来源'}).boundingBox();
    const menu=await dialog.getByRole('listbox',{name:'消息来源'}).boundingBox();
    return Math.abs(menu!.y-(trigger!.y+trigger!.height+6));
  }).toBeLessThan(2);
});
