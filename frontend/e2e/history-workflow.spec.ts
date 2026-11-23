import {test,expect} from '@playwright/test';
for(const mode of ['source-failure','output-truncated','citation-repair','pause-resume']){
test(`large history assembles complete results: ${mode}`,async({page,request})=>{
 await request.post('/api/__test__/reset',{data:{case:mode==='pause-resume'?'pause-history':'long-history',history_failure:mode==='source-failure',history_output_truncated:mode==='output-truncated',history_bad_citation:mode==='citation-repair'}});
 await page.goto('/');await page.getByRole('button',{name:'设置',exact:true}).click();
 await page.getByRole('button',{name:'配置模型',exact:true}).click();
 const model=page.getByRole('dialog',{name:'模型配置'});
 await model.getByLabel('服务地址',{exact:true}).fill('https://synthetic.example/chat/completions');
 await model.getByLabel('模型 ID',{exact:true}).fill('synthetic');
 await model.getByLabel('API 密钥',{exact:true}).fill('synthetic-key');
 await model.getByLabel('上下文上限',{exact:true}).fill(['source-failure','pause-resume'].includes(mode)?'24000':'500000');
 await model.getByLabel('最大输出',{exact:true}).fill('1024');
 await model.getByRole('button',{name:'保存配置',exact:true}).click();
 await model.getByRole('button',{name:'检查连接',exact:true}).click();
 await model.getByLabel('预算依据（供应商文档HTTPS地址）').fill('https://docs.example/budget');
 await model.getByLabel('我已核对供应商文档，支持以上文本上下文和最大输出预算').check();
 await model.getByRole('button',{name:'确认文本预算',exact:true}).click();
 await model.getByRole('button',{name:'完成',exact:true}).click();
 await page.getByRole('button',{name:'工作台',exact:true}).click();
 await page.getByRole('button',{name:'查看 商家甲',exact:true}).click();
 const customer=page.getByRole('dialog').first();
 await customer.getByRole('button',{name:'同步并整理此客户',exact:true}).click();
 const status=customer.getByRole('region',{name:'当前客户同步状态'});
 if(mode!=='citation-repair')await expect(status.getByRole('group',{name:'长历史整理进度'})).toBeVisible();
 if(mode==='source-failure'){
 await expect(status.getByText('消息已同步，整理未完成',{exact:true})).toBeVisible();
 await expect(status.getByText('已校验的分段已保存，继续整理时可复用。')).toBeVisible();
 const {retry_at}=await (await request.post('/api/__test__/history-recover')).json();
 await status.getByRole('button',{name:'查看同步详情',exact:true}).click();
 const failed=page.getByRole('dialog',{name:'整理记录'});
 await expect.poll(()=>Date.now()/1000,{timeout:7000}).toBeGreaterThanOrEqual(retry_at);
 await failed.getByRole('button',{name:'重新同步',exact:true}).click();
 await failed.getByRole('button',{name:'关闭弹窗',exact:true}).click();
 }
 if(mode==='pause-resume'){
   await expect(status.getByText('整理已暂停，可继续',{exact:true})).toBeVisible();
   await status.getByRole('button',{name:'查看同步详情',exact:true}).click();
   const paused=page.getByRole('dialog',{name:'整理记录'});
   await expect(paused.getByText(/模型请求 20 次/)).toBeVisible();
   await paused.getByRole('button',{name:'继续整理',exact:true}).click();
   await expect.poll(async()=>{
     const jobs=await(await request.get('/api/operations?account_id=acct-1')).json();
     return jobs.items[0].report?.analysis_outcome;
   }).toBe('updated');
   const jobs=await(await request.get('/api/operations?account_id=acct-1')).json();
   expect(jobs.items[0].counts.analysis_chunks_reused).toBeGreaterThan(0);
   expect(jobs.items[0].counts.model_requests).toBeLessThan(20);
   return;
 }
 await expect(status.getByText('整理完成',{exact:true})).toBeVisible();
 const historyProgress=status.getByRole('group',{name:'长历史整理进度'});
 if(mode==='source-failure')await expect(historyProgress.getByText(/分段提取 \d+ \/ \d+ · 复用 [1-9]\d* 段/)).toBeVisible();
 await expect(customer.getByText(/^(约)?12方$/)).toBeVisible();
 const jobs=await(await request.get('/api/operations?account_id=acct-1')).json();
 const latest=jobs.items[0];if(mode==='source-failure')expect(latest.counts.analysis_chunks_reused).toBeGreaterThan(0);else if(mode==='output-truncated')expect(latest.counts.analysis_refinements).toBeGreaterThan(0);else expect(latest.counts.model_source_unknown).toBeGreaterThan(0);
 expect(latest.counts.analysis_chunks_completed).toBe(latest.counts.analysis_chunks_total);
 expect(latest.counts.analysis_material_completed).toBe(latest.counts.analysis_material_total);
 await status.getByRole('button',{name:'查看同步详情',exact:true}).click();
 const records=page.getByRole('dialog',{name:'整理记录'});
 if(mode!=='citation-repair')await expect(records.getByRole('group',{name:'长历史整理进度'})).toBeVisible();
 await records.getByText('诊断详情',{exact:true}).click();
 await expect(records.getByText(/UTF-8 保守上界/)).toBeVisible();
 if(mode==='citation-repair')await expect(records.getByText(/引用问题：未知编号 1/)).toBeVisible();
});

}
