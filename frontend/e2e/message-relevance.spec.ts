import { expect, test } from "@playwright/test";

test("单客户试用显示分级进度，并提交选中的原文修订", async ({ page, request }) => {
  await request.post("/api/__test__/reset");
  const record = {
    id:"relevance-test", scope:{account_id:"acct-1",contact_id:"merchant-a"},
    contact_name_snapshot:"商家甲", action:"sync_and_organize", state:"succeeded", phase:"completed",
    source_state:"succeeded", error_code:null, available_actions:[], updated_at:"2026-11-23T10:00:00Z",
    counts:{relevance_total:339,relevance_high:48,relevance_medium:67,relevance_low:224,
      analysis_chunks_total:2,analysis_chunks_completed:1,analysis_material_completed:18,analysis_material_total:48},
    items:[], report:{version:1,scope_label:"商家甲",source_outcome:"completed",analysis_outcome:"updated",contacts:[],issues:[]}
  };
  const submissions: Array<{options:{text_strategy:string;relevance_review_refs:unknown[]}}> = [];
  await page.route("**/api/operations", route => {
    submissions.push(route.request().postDataJSON());
    return route.fulfill({json:record,status:202});
  });
  await page.route("**/api/operations/relevance-test?**", route => route.fulfill({json:record}));
  await page.route("**/api/operations/relevance-test/relevance?**", route => route.fulfill({json:{
    total:1, sources:{room:{title:"业务会话"}}, items:[
      {message_id:"selected-msg",revision:2,level:"medium",preview:"按上次要求",day:"2026-11-23",reason_codes:["context_required"]}
    ]
  }}));
  await page.goto("/");
  await page.getByRole("button",{name:"查看 商家甲",exact:true}).click();
  await page.getByRole("button",{name:"高价值整理",exact:true}).click();
  await expect(page.getByText("已筛选 339 条 · 高 48 · 中 67 · 低 224").first()).toBeVisible();
  await page.getByRole("button",{name:"查看同步详情",exact:true}).click();
  const history = page.getByRole("dialog",{name:"整理记录"});
  await history.getByText("查看分级与复核",{exact:true}).click();
  await history.getByRole("checkbox",{name:/按上次要求/}).check();
  await history.getByRole("button",{name:"整理所选原文（1）"}).click();
  await expect.poll(()=>submissions.length).toBe(2);
  expect(submissions[0].options.text_strategy).toBe("relevance");
  expect(submissions[1].options.relevance_review_refs).toEqual([{message_id:"selected-msg",revision:2}]);
});
