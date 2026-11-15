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
