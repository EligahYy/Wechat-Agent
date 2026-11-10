import { esc } from "./client.js";
export function taskStages(s) {
  if (s.phase === "update")
    return `<p class="meta">${esc(s.stage_detail)}；开始后复用已有分册。</p>`;
  if (!s.total_pages)
    return `<p class="meta">${esc(s.action_hint || "开始后整理该联系人的完整授权聊天。")}</p>`;
  const stages = [
    ["collect", "原始分册"],
    ["merge", "合并资料"],
    ["summarize", "总结档案"],
    ["review", "来源复核"],
    ["publish", "保存档案"],
  ];
  const current =
    s.phase === "done"
      ? stages.length
      : stages.findIndex(([key]) => key === s.phase);
  return `<ol class="analysis-stages" aria-label="客户整理阶段">${stages.map(([key, label], index) => `<li class="${index < current ? "complete" : index === current ? "current" : ""}" ${index === current ? 'aria-current="step"' : ""}>${esc(label)}</li>`).join("")}</ol><p class="meta">原始资料：分册 ${s.completed_pages} / ${s.total_pages} · 已整理 ${s.processed_messages} / ${s.source_messages} 条</p><p>${esc(s.stage_detail)}</p>${s.stage_total ? `<progress class="stage-progress" max="${s.stage_total}" value="${s.stage_completed}" aria-label="${esc(s.phase_label)}进度"></progress>` : ""}`;
}
