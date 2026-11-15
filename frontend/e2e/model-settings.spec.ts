import {test,expect} from '@playwright/test';
test.beforeEach(async({page,request})=>{await request.post('/api/__test__/reset');await page.goto('/');});
test('saving model config is separate from explicit probe and never refills secrets',async({page})=>{
  const checks:string[]=[];
  page.on('request',request=>{if(request.url().endsWith('/api/model/check'))checks.push(request.method());});
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await page.getByRole('button',{name:'配置模型',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'模型配置',exact:true});
  await dialog.getByLabel('服务地址',{exact:true}).fill('https://synthetic.example/chat/completions');
  await dialog.getByLabel('模型 ID',{exact:true}).fill('synthetic');
  await dialog.getByLabel('API 密钥',{exact:true}).fill('browser-test-key');
  await dialog.getByLabel('上下文上限',{exact:true}).fill('16000');
  await dialog.getByLabel('最大输出',{exact:true}).fill('1000');
  await dialog.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect(dialog.getByText('配置已保存，尚未检查连接',{exact:true})).toBeVisible();
  expect(checks).toEqual([]);
  await expect(dialog.getByLabel('API 密钥',{exact:true})).toHaveValue('');
  await dialog.getByRole('button',{name:'检查连接',exact:true}).click();
  await expect(dialog.getByText('连接检查通过',{exact:true})).toBeVisible();
  await expect(dialog.locator('.model-connection-status[data-state=passed] .connection-status-indicator')).toHaveCSS('background-color','rgb(21, 128, 61)');
  await expect(dialog.getByText(/容量和视觉能力尚未验证/)).toBeVisible();
  expect(checks).toEqual(['POST']);
  await dialog.getByRole('button',{name:'完成',exact:true}).click();
  await page.reload();
  await page.getByRole('button',{name:'设置',exact:true}).click();
  await page.getByRole('button',{name:'配置模型',exact:true}).click();
  await expect(dialog.getByLabel('API 密钥',{exact:true})).toHaveValue('');
  await expect(dialog.getByLabel('模型 ID',{exact:true})).toHaveValue('synthetic');
});
test('reopened running check refreshes to finished without another paid request',async({page,request})=>{
 await request.post('/api/__test__/reset');let reads=0;
 await page.route('**/api/settings',async route=>{const response=await route.fetch();const settings=await response.json();await route.fulfill({json:{...settings,model:{state:'configured',model_id:'synthetic',connection_state:reads<3?'running':'passed'}}});});
 await page.route('**/api/model?*',route=>{reads++;return route.fulfill({json:{account_id:'acct-1',version:1,configured:true,endpoint:'https://synthetic.example/chat/completions',model_id:'synthetic',response_mode:'json_object',context_tokens:16000,max_output_tokens:1000,connection:{state:reads<3?'running':'passed',capacity_verified:false,vision_verified:false}}});});
 await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'配置模型'}).click();
 await expect(page.getByRole('dialog',{name:'模型配置'}).getByText('连接检查通过',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'检查连接',exact:true})).toBeEnabled();
 await page.getByRole('button',{name:'完成',exact:true}).click();
 await expect(page.locator('.settings-row .model-connection-status')).toHaveText('连接检查通过');
});

test('edited model settings remove the passed indicator until saved and rechecked',async({page})=>{
 await page.route('**/api/model?*',route=>route.fulfill({json:{account_id:'acct-1',version:1,configured:true,endpoint:'https://synthetic.example/chat/completions',model_id:'synthetic',response_mode:'json_object',context_tokens:16000,max_output_tokens:1000,connection:{state:'passed',capacity_verified:false,vision_verified:false}}}));
 await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'配置模型'}).click();
 const dialog=page.getByRole('dialog',{name:'模型配置'});
 await expect(dialog.locator('.model-connection-status[data-state=passed]')).toBeVisible();
 await dialog.getByLabel('模型 ID',{exact:true}).fill('different-model');
 await expect(dialog.locator('.model-connection-status')).toHaveText('配置已修改，保存后重新检查');
 await expect(dialog.locator('.model-connection-status[data-state=passed]')).toHaveCount(0);
 await expect(dialog.getByRole('button',{name:'检查连接',exact:true})).toBeDisabled();
});

for(const theme of ['light','dark'] as const){
 test(`model connection result stays consistent in settings and dialog in ${theme} theme`,async({page})=>{
  let state='failed';
  const config=()=>({account_id:'acct-1',version:1,configured:true,endpoint:'https://synthetic.example/chat/completions',model_id:'synthetic',response_mode:'json_object',context_tokens:16000,max_output_tokens:1000,connection:{state,capacity_verified:false,vision_verified:false}});
  await page.route('**/api/settings',async route=>{const response=await route.fetch();const settings=await response.json();await route.fulfill({json:{...settings,preferences:{...settings.preferences,appearance:theme},model:{state:'configured',model_id:'synthetic',connection_state:state}}});});
  await page.route('**/api/model?*',route=>route.fulfill({json:config()}));
  await page.route('**/api/model/check',route=>{state='passed';return route.fulfill({json:config()});});
  await page.reload();await page.getByRole('button',{name:'设置',exact:true}).click();
  const row=page.locator('.settings-row').filter({has:page.getByRole('button',{name:'配置模型',exact:true})});
  await expect(row.getByRole('status')).toHaveText('连接检查未通过');
  await page.getByRole('button',{name:'配置模型',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'模型配置'});
  await expect(dialog.locator('.connection-status-indicator')).toHaveCSS('background-color',theme==='light'?'rgb(189, 48, 56)':'rgb(255, 136, 146)');
  await dialog.getByRole('button',{name:'检查连接',exact:true}).click();
  await expect(dialog.locator('.model-connection-status')).toHaveText('连接检查通过');
  await expect(dialog.locator('.connection-status-indicator')).toHaveCSS('background-color',theme==='light'?'rgb(21, 128, 61)':'rgb(115, 220, 162)');
  await expect(dialog.getByText(/容量和视觉能力尚未验证/)).toBeVisible();
  await dialog.getByRole('button',{name:'完成',exact:true}).click();
  await expect(row.getByRole('status')).toHaveText('连接检查通过');
  await expect(row.locator('.connection-status-indicator')).toHaveCSS('background-color',theme==='light'?'rgb(21, 128, 61)':'rgb(115, 220, 162)');
 });
}
