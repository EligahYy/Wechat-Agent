import {test,expect} from '@playwright/test';
test.beforeEach(async({page,request})=>{await request.post('/api/__test__/reset',{data:{case:'profile-ready'}});await page.goto('/');await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();});
test('profile cards edit persist restore model values and show exact evidence',async({page})=>{
 const profile=page.getByRole('dialog').first();
 await expect(profile.getByRole('heading',{name:'货品资料',exact:true})).toBeVisible();
 await expect(profile.getByText('约12方',{exact:true})).toBeVisible();
 await profile.getByRole('button',{name:'查看 货量 来源',exact:true}).click();
 const evidence=page.getByRole('dialog',{name:'资料来源'});await expect(evidence.getByText(/新批约12方/)).toBeVisible();await expect(evidence.getByText('商家甲',{exact:true})).toBeVisible();await evidence.getByRole('button',{name:'关闭弹窗'}).click();
 await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();
 const editor=page.getByRole('dialog',{name:'编辑货品资料'});
 await expect(editor.getByRole('button',{name:'保存资料'})).toBeDisabled();
 await editor.getByLabel('货量',{exact:true}).fill('人工确认15方');await editor.getByLabel('货品补充资料').fill('需要拍照');await editor.getByRole('button',{name:'保存资料'}).click();await expect(editor).not.toBeVisible();
 await expect(profile.getByText('人工确认15方',{exact:true})).toBeVisible();await expect(profile.getByText('需要拍照',{exact:true})).toBeVisible();
 await page.reload();await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();await expect(profile.getByText('人工确认15方',{exact:true})).toBeVisible();
 await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();await editor.getByRole('button',{name:'恢复 货量 模型值'}).click();await editor.getByRole('button',{name:'保存资料'}).click();await expect(profile.getByText('约12方',{exact:true})).toBeVisible();
});
test('number edits persist without changing shipment stage',async({page})=>{
 const profile=page.getByRole('dialog').first();await profile.getByRole('tab',{name:'备货记录',exact:true}).click();await expect(profile.getByText('询价',{exact:true})).toBeVisible();
 await profile.getByRole('button',{name:'编辑单号'}).click();const editor=page.getByRole('dialog',{name:'编辑单号'});await editor.getByLabel('单号（每行一个）').fill('A-001\nB-002\nA-001');await editor.getByRole('button',{name:'保存单号'}).click();await expect(profile.getByText('A-001',{exact:true})).toBeVisible();await expect(profile.getByText('询价',{exact:true})).toBeVisible();
});
test('conflict keeps the editor draft and allows explicit version reconciliation',async({page,request})=>{
 const profile=page.getByRole('dialog').first();await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();const editor=page.getByRole('dialog',{name:'编辑货品资料'});await editor.getByLabel('货量',{exact:true}).fill('我的修改');
 await request.patch('/api/contacts/merchant-a/manual',{data:{account_id:'acct-1',expected_version:0,notes:{goods:'另一处已更新'}}});await editor.getByRole('button',{name:'保存资料'}).click();await expect(editor.getByRole('alert')).toContainText('已变化');await expect(editor.getByLabel('货量',{exact:true})).toHaveValue('我的修改');
 await editor.getByRole('button',{name:'保留填写并核对最新版本'}).click();await expect(editor.getByLabel('货品补充资料')).toHaveValue('另一处已更新');await editor.getByRole('button',{name:'保存资料'}).click();await expect(profile.getByText('我的修改',{exact:true})).toBeVisible();
});
test('detail avatar follows all four role colors in light and dark themes',async({page})=>{
 const dialog=page.getByRole('dialog').first();
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;},theme);
  for(const name of ['服务商','平台','待识别','商家']){
   await dialog.getByRole('button',{name:'修改身份',exact:true}).click();await page.getByRole('menuitemradio',{name,exact:true}).click();await expect(page.getByRole('menu')).toHaveCount(0);
   await expect.poll(()=>dialog.locator('.detail-heading').evaluate(node=>{const avatar=getComputedStyle(node.querySelector('.avatar')!),tag=getComputedStyle(node.querySelector('.role-trigger .role-tag')!);return avatar.backgroundColor===tag.backgroundColor&&avatar.color===tag.color;})).toBe(true);
  }
 }
});
test('overlapping field and note conflicts show current server values before choosing a resolution',async({page,request})=>{
 const profile=page.getByRole('dialog').first();await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();
 const editor=page.getByRole('dialog',{name:'编辑货品资料'});await editor.getByLabel('货量',{exact:true}).fill('我的15方');await editor.getByLabel('货品补充资料').fill('我的说明');
 const changed=await request.patch('/api/contacts/merchant-a/manual',{data:{account_id:'acct-1',expected_version:0,fields:{'goods.volume':'最新20方'},notes:{goods:'最新说明'}}});expect(changed.ok()).toBeTruthy();
 await editor.getByRole('button',{name:'保存资料'}).click();await expect(editor.getByRole('alert')).toContainText('已变化');
 await editor.getByRole('button',{name:'保留填写并核对最新版本'}).click();
 await expect(editor.getByText('最新20方',{exact:true})).toBeVisible();await expect(editor.getByText('最新说明',{exact:true})).toBeVisible();
 await expect(editor.getByLabel('货量',{exact:true})).toHaveValue('我的15方');await expect(editor.getByRole('button',{name:'保存资料'})).toBeDisabled();
 await editor.getByRole('button',{name:'保留 货量 我的填写',exact:true}).click();await expect(editor.getByRole('button',{name:'保存资料'})).toBeDisabled();
 await editor.getByRole('button',{name:'采用 货品补充资料 最新值',exact:true}).click();await editor.getByRole('button',{name:'保存资料'}).click();await expect(editor).not.toBeVisible();
 const result=await(await request.get('/api/contacts/merchant-a/profile?account_id=acct-1')).json();expect(result.effective.goods.volume.value).toBe('我的15方');expect(result.manual.notes.goods).toBe('最新说明');
});
for(const resolution of ['keep','adopt'])test(`number conflict displays latest numbers and requires an explicit ${resolution} choice`,async({page,request})=>{
 const data=await(await request.get('/api/contacts/merchant-a/profile?account_id=acct-1')).json();const shipment=data.shipments[0];
 const profile=page.getByRole('dialog').first();await profile.getByRole('tab',{name:'备货记录',exact:true}).click();await profile.getByRole('button',{name:'编辑单号'}).click();const editor=page.getByRole('dialog',{name:'编辑单号'});await editor.getByLabel('单号（每行一个）').fill('MY-NEW');
 const changed=await request.patch(`/api/shipments/${encodeURIComponent(shipment.shipment_id)}/numbers`,{data:{account_id:'acct-1',contact_id:'merchant-a',expected_version:shipment.version,numbers:['OTHER-NEW']}});expect(changed.ok()).toBeTruthy();
 await editor.getByRole('button',{name:'保存单号'}).click();await expect(editor.getByRole('alert')).toContainText('已变化');await editor.getByRole('button',{name:'保留填写并核对最新版本'}).click();
 await expect(editor.getByText('OTHER-NEW',{exact:true})).toBeVisible();await expect(editor.getByLabel('单号（每行一个）')).toHaveValue('MY-NEW');await expect(editor.getByRole('button',{name:'保存单号'})).toBeDisabled();
 if(resolution==='keep'){await editor.getByRole('button',{name:'保留我的单号',exact:true}).click();await editor.getByRole('button',{name:'保存单号'}).click();await expect(editor).not.toBeVisible();}
 else{await editor.getByRole('button',{name:'采用最新单号',exact:true}).click();await expect(editor.getByLabel('单号（每行一个）')).toHaveValue('OTHER-NEW');await expect(editor.getByRole('button',{name:'保存单号'})).toBeDisabled();await editor.getByRole('button',{name:'取消',exact:true}).click();}
 const result=await(await request.get('/api/contacts/merchant-a/profile?account_id=acct-1')).json();expect(result.shipments[0].numbers).toEqual([resolution==='keep'?'MY-NEW':'OTHER-NEW']);expect(result.shipments[0].stage).toBe('询价');
});
test('adopting a conflicting field preserves the latest server value without another write',async({page,request})=>{
 const profile=page.getByRole('dialog').first();await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();const editor=page.getByRole('dialog',{name:'编辑货品资料'});await editor.getByLabel('货量',{exact:true}).fill('草稿15方');
 await request.patch('/api/contacts/merchant-a/manual',{data:{account_id:'acct-1',expected_version:0,fields:{'goods.volume':'最新20方'}}});
 await editor.getByRole('button',{name:'保存资料'}).click();await editor.getByRole('button',{name:'保留填写并核对最新版本'}).click();await editor.getByRole('button',{name:'采用 货量 最新值',exact:true}).click();
 await expect(editor.getByLabel('货量',{exact:true})).toHaveValue('最新20方');await expect(editor.getByRole('button',{name:'保存资料'})).toBeDisabled();await editor.getByRole('button',{name:'取消',exact:true}).click();
 const current=await(await request.get('/api/contacts/merchant-a/profile?account_id=acct-1')).json();expect(current.manual_version).toBe(1);expect(current.effective.goods.volume.value).toBe('最新20方');
});
test('restoring a model field also requires resolving a newer manual override',async({page,request})=>{
 await request.patch('/api/contacts/merchant-a/manual',{data:{account_id:'acct-1',expected_version:0,fields:{'goods.volume':'人工15方'}}});await page.reload();await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 const profile=page.getByRole('dialog').first();await profile.getByRole('button',{name:'编辑货品资料',exact:true}).click();const editor=page.getByRole('dialog',{name:'编辑货品资料'});await editor.getByRole('button',{name:'恢复 货量 模型值',exact:true}).click();
 await request.patch('/api/contacts/merchant-a/manual',{data:{account_id:'acct-1',expected_version:1,fields:{'goods.volume':'最新20方'}}});
 await editor.getByRole('button',{name:'保存资料'}).click();await editor.getByRole('button',{name:'保留填写并核对最新版本'}).click();await expect(editor.getByText('最新20方',{exact:true})).toBeVisible();await expect(editor.getByRole('button',{name:'保存资料'})).toBeDisabled();
 await editor.getByRole('button',{name:'保留 货量 我的填写',exact:true}).click();await editor.getByRole('button',{name:'保存资料'}).click();await expect(editor).not.toBeVisible();
 const current=await(await request.get('/api/contacts/merchant-a/profile?account_id=acct-1')).json();expect(current.effective.goods.volume.value).toBe('约12方');expect(current.manual.fields['goods.volume']).toBeUndefined();
});
