import { esc, time } from "./client.js";
export const stageNames = {
  needs: "需求确认",
  quoting: "报价沟通",
  decision: "商家决策",
  preparing: "备货中",
  fulfillment: "已走货 · 后续对接",
  reported_shipped: "已报告发货",
  closed: "已结束",
};
export function mediaControls(message) {
  return ["3", "image"].includes(message.type)
    ? `<button data-image="${esc(message.id)}">查看图片与识别文字</button>${message.image_text?.confirmed_text ? `<div class="verified-text"><span class="meta">图片文字 · 已人工核对</span><p>${esc(message.image_text.confirmed_text)}</p></div>` : ""}`
    : "";
}
export function evidence(refs, d) {
  const ids = new Set(refs.map((r) => r.id));
  return `<details class="proof"><summary>查看来源</summary>${d.evidence
    .filter((m) => ids.has(m.id))
    .map(
      (m) =>
        `<article class="evidence"><p class="meta">${esc(m.conversation)} · ${esc(time(m.event_time))} 北京时间</p><p>${esc(m.text)}</p>${mediaControls(m)}</article>`,
    )
    .join("")}</details>`;
}
function warning(item) {
  return item.quality_warnings?.length
    ? '<p class="meta">数字字段待核对，请以原文为准。</p>'
    : "";
}
function correction(section, id, item) {
  return `<details><summary>纠正这条内容</summary><label>核对来源后的表述<input maxlength="500" id="correct-${id}" value="${esc(item.text)}"></label><button data-operation="correct" data-target="${section}:${id}" data-input="correct-${id}">保存纠正</button></details>`;
}
export function customerHTML(d) {
  const batches = Object.entries(d.body.batches).sort((a, b) =>
    (b[1].event_time || "").localeCompare(a[1].event_time || ""),
  );
  const pending = Object.entries(d.body.decisions).filter(
    ([, q]) => !q.resolved,
  );
  const allActions = Object.entries(d.body.actions);
  const actions = allActions.filter(
    ([, a]) => !["done", "cancelled"].includes(a.state),
  );
  const historyActions = allActions.filter(([, a]) =>
    ["done", "cancelled"].includes(a.state),
  );
  return `<div class="customer-heading"><span class="badge">${d.body.relationship === "merchant" ? "商家" : "待识别线索"}</span>${d.body.paused ? '<span class="badge">已暂停联系</span>' : ""}${d.needs_update ? '<span class="badge attention">新进展待整理</span>' : ""}<p>${esc(d.location.remark || d.location.nickname || "姓名待同步")} <span class="meta">${esc(d.location.alias || d.source_id)}</span></p><p class="meta">${d.location.conversations.map((c) => esc(c.title)).join(" / ")}</p><div class="toolbar"><button id="copy-contact-name">复制联系人名称</button><button data-operation="pause" data-value="${!d.body.paused}">${d.body.paused ? "恢复联系建议" : "暂停联系建议"}</button>${d.actor_id ? '<button id="exempt-customer">加入免跟进白名单</button>' : ""}</div></div><div id="image-view" hidden></div>
<div class="detail-tabs" role="tablist" aria-label="客户档案内容">${Object.entries(
    {
      overview: "资料概览",
      work: "批次与行动",
      timeline: "完整时间线",
      journal: "人工跟进",
    },
  )
    .map(
      ([id, n], i) =>
        `<button data-detail-tab="${id}" role="tab" aria-selected="${i === 0}">${n}${id === "work" && pending.length ? ` · ${pending.length}项待确认` : ""}</button>`,
    )
    .join("")}</div>
<div data-detail-panel="overview">${d.body.quality_issues?.length ? `<section class="insight-card"><h3>有内容需要核实</h3><p>${d.body.quality_issues.length}条推断尚未确认归属或表述。它们保留在待核实线索中，不作为确定事实。</p></section>` : ""}<section class="section"><h3>客户资料与来源事实</h3>${
    Object.entries(d.body.notes)
      .map(
        ([id, n]) =>
          `<article class="insight-card"><p>${esc(n.text)}</p>${warning(n)}${evidence(n.evidence, d)}${correction("notes", id, n)}</article>`,
      )
      .join("") || "<p>尚未形成已核实资料，可查看完整时间线和资料分册。</p>"
  }</section><section class="section"><h3>资料覆盖</h3><p>相关归档 ${d.body.coverage.source_messages ?? "未知"} 条 · 已整理 ${d.body.coverage.processed_messages ?? d.body.coverage.messages} 条 · 分册 ${d.body.coverage.pages || 0}</p><p class="meta">${d.body.coverage.complete_context ? "相关归档文本已分册整理。" : "包含未识别媒体或待核实内容，不能把未提取解释为没有需求。"}</p><button data-packets="1">查看已保存资料分册</button><div id="packet-ledger"></div>${d.body.unattributed?.length ? `<details><summary>待核实线索（${d.body.unattributed.length}）</summary>${d.body.unattributed.map((x) => `<article class="insight-card"><p>待核实推断：${esc(x.text)}</p>${evidence(x.evidence, d)}</article>`).join("")}</details>` : ""}</section><details class="section"><summary>档案更新记录</summary><button id="load-customer-history">查看最近30次更新</button><div id="customer-history"></div></details></div>
<div data-detail-panel="work" hidden><section class="section"><h3>备货批次</h3>${
    batches
      .map(
        ([id, b]) =>
          `<article class="insight-card"><span class="badge">${stageNames[b.stage]}</span>${b.stage_locked ? '<span class="badge">人工确认阶段</span>' : ""}<p>${esc(b.text)}</p>${warning(b)}${b.manual_stage_note ? `<p class="meta">人工备注：${esc(b.manual_stage_note)}</p>` : ""}${evidence(b.evidence, d)}${correction("batches", id, b)}<details><summary>人工确认批次阶段</summary><p class="meta">人工确认优先于模型，直到你选择恢复自动判断。此操作不代表平台已核实实际物流结果。</p><label>阶段<select id="stage-${id}">${Object.entries(
            stageNames,
          )
            .map(
              ([k, v]) =>
                `<option value="${k}" ${b.stage === k ? "selected" : ""}>${v}</option>`,
            )
            .join(
              "",
            )}<option value="auto">恢复自动判断</option></select></label><label>判断依据<input id="stage-note-${id}" maxlength="500" value="${esc(b.manual_stage_note || "")}" placeholder="例如已核对运单轨迹，实际已发车"></label><button data-save-stage="${id}">保存阶段判断</button></details></article>`,
      )
      .join("") || "<p>尚无具体批次。初步沟通和资料仍保留在概览与时间线。</p>"
  }</section><section class="section"><h3>下一步</h3>${actions.map(([id, a]) => `<article class="insight-card"><span class="badge">${{ open: "待处理", waiting: "等待回复", done: "已完成", cancelled: "已取消", proposed: "待确认建议", historical_unresolved: "历史待核实" }[a.state] || a.state}</span><p>${esc(a.text)}</p><p class="meta">${esc(a.reason)} · ${esc(a.due_date || "未约定日期")}</p>${evidence(a.evidence, d)}${a.state === "proposed" ? `<p class="meta">请核对来源覆盖与实际责任归属。</p><button data-operation="confirm_action" data-target="${id}" data-value="true">确认由我跟进</button>` : ""}${["open", "waiting"].includes(a.state) ? `<div class="toolbar spaced"><button data-operation="action" data-target="${id}" data-value="done">标记已处理</button><button data-operation="action" data-target="${id}" data-value="waiting">等待回复</button><button data-operation="action" data-target="${id}" data-value="cancelled">取消这项待办</button></div><label>下次联系日期<input type="date" id="schedule-${id}" value="${esc(a.due_date || "")}"></label><button data-operation="schedule" data-target="${id}">保存日期</button><button data-draft="${id}" ${d.can_followup ? "" : "disabled"}>生成跟进草稿</button><div id="draft-${id}"></div>` : ""}</article>`).join("") || "<p>当前未识别出明确的未完成行动；可在时间线核对来源。</p>"}${historyActions.length ? `<details><summary>已处理与取消的行动（${historyActions.length}）</summary>${historyActions.map(([, a]) => `<article class="insight-card"><span class="badge">${a.state === "done" ? "已完成" : "已取消"}</span><p>${esc(a.text)}</p>${evidence(a.evidence, d)}</article>`).join("")}</details>` : ""}</section><section class="section"><h3>关键确认</h3>${pending.map(([id, q]) => `<article class="insight-card"><h4>${esc(q.text)}</h4>${q.batch ? `<p class="meta">对应批次：${esc(d.body.batches[q.batch]?.text || "")}</p>` : ""}${q.impact ? `<p class="meta">确认用途：${esc(q.impact)}</p>` : ""}${evidence(q.evidence, d)}<label>你的判断${id === "role" ? `<select id="decision-${id}"><option value="merchant">商家</option><option value="non_target">同事／服务商等非目标客户</option><option value="candidate">暂不能确定</option></select>` : `<textarea id="decision-${id}" maxlength="500" rows="3" placeholder="填写影响当前需求的明确判断"></textarea>`}</label><button data-operation="decision" data-target="${id}">保存判断</button></article>`).join("") || "<p>暂无需要处理的关键确认。</p>"}</section></div>
<div data-detail-panel="timeline" hidden><section class="section"><h3>从首次接触开始的完整时间线</h3><p class="meta">保留所有相关消息；分页和搜索只影响展示，不删除分析来源。</p><form id="customer-timeline-search" class="toolbar"><label class="candidate-search">查找原文<input name="q" maxlength="200" placeholder="单号或原文关键词"></label><button>查找</button></form><button data-ledger="1">查看全部聊天记录</button><div id="source-ledger"></div></section></div>
<div data-detail-panel="journal" hidden><section class="section"><h3>记录人工跟进</h3><p class="meta">这里只记录你实际完成的沟通，系统不会发送微信，也不会将“已联系”当作已发货。</p><form id="customer-followup-form"><label>沟通情况<select name="outcome"><option value="contacted">已联系</option><option value="replied">已收到反馈</option><option value="no_reply">暂未回复</option><option value="note">补充备注</option></select></label><label>跟进内容<textarea name="note" maxlength="1000" rows="4" required placeholder="记录实际沟通内容与反馈"></textarea></label><label>关联待办（可选）<select name="action_id"><option value="">只记客户跟进，不改变待办</option>${actions.map(([id, a]) => `<option value="${id}">${esc(a.text)}</option>`).join("")}</select></label><label>待办状态<select name="action_state" disabled><option value="keep">保持原状态</option><option value="waiting">等待回复</option><option value="done">已处理</option><option value="cancelled">取消待办</option></select></label><label>下次联系日期<input name="next_date" type="date" disabled></label><button class="primary">保存人工跟进</button></form><button class="spaced" data-journal="1">查看跟进记录</button><div id="customer-journal"></div></section></div>`;
}
