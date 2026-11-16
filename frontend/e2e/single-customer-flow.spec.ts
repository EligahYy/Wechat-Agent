import {test,expect} from '@playwright/test';
test('reviewed text budget enables real operation workflow and profile publication',async({page,request})=>{
 await request.post('/api/__test__/reset');await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click();await page.getByRole('button',{name:'配置模型',exact:true}).click();
 const model=page.getByRole('dialog',{name:'模型配置'});
 await model.getByLabel('服务地址',{exact:true}).fill('https://synthetic.example/chat/completions');await model.getByLabel('模型 ID',{exact:true}).fill('synthetic');await model.getByLabel('API 密钥',{exact:true}).fill('synthetic-key');await model.getByLabel('上下文上限',{exact:true}).fill('128000');await model.getByLabel('最大输出',{exact:true}).fill('8192');await model.getByRole('button',{name:'保存配置',exact:true}).click();await model.getByRole('button',{name:'检查连接',exact:true}).click();
 await expect(model.getByRole('button',{name:'确认文本预算'})).toBeDisabled();await model.getByLabel('预算依据（供应商文档HTTPS地址）').fill('https://docs.example/budget');await model.getByLabel('我已核对供应商文档，支持以上文本上下文和最大输出预算').check();await model.getByRole('button',{name:'确认文本预算'}).click();await expect(model.getByText('文本预算已核对，可整理文本资料')).toBeVisible();
 await model.getByRole('button',{name:'完成',exact:true}).click();await page.getByRole('button',{name:'工作台',exact:true}).click();await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 const customer=page.getByRole('dialog').first();await customer.getByRole('button',{name:'同步并整理此客户',exact:true}).click();await expect(customer.getByText('约12方',{exact:true})).toBeVisible();await expect(customer.getByRole('region',{name:'当前客户同步状态'})).toContainText('整理完成');
 await customer.getByRole('button',{name:'同步并整理此客户',exact:true}).click();await expect(customer.getByRole('region',{name:'当前客户同步状态'})).toContainText('输入未变化，无需更新');
});
