const $ = (s) => document.querySelector(s),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
let view = "today",
  documents = [],
  selected,
  focusBefore,
  busy = false,
  candidatePage = 1;
const stages = {
  needs: "需求确认",
  quoting: "报价沟通",
  decision: "商家决策",
  preparing: "备货中",
  reported_shipped: "已报告发货",
  closed: "已结束",
};
async function api(path, body) {
  const r = await fetch("/api/workspace/" + path, {
    method: body ? "POST" : "GET",
    headers: body
      ? {
          "Content-Type": "application/json",
          "X-CSRF-Token": $("meta[name=csrf]").content,
        }
      : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json();
  if (!r.ok) throw Error(d.error || "请求失败");
  return d;
}
async function refresh() {
  const data = await api("documents");
  documents = data.items;
  $("#status").textContent = data.stale_documents
    ? `${data.stale_documents} 份档案依据已变化，已暂时退出展示，请重新分析。`
    : "";
  render();
}
function active(d) {
  return (d.today_action_ids || []).map((id) => [id, d.body.actions[id]]);
}
function render() {
  document
    .querySelectorAll("nav button")
    .forEach((b) =>
      b.setAttribute(
        "aria-current",
        b.dataset.view === view ? "page" : "false",
      ),
    );
  $("#title").textContent = {
    today: "今天该联系谁",
    customers: "客户",
    review: "待确认",
    pilot: "试点与进度",
  }[view];
  if (view === "pilot") {
    pilot();
    return;
  }
  const list = documents.filter((d) =>
    view === "today"
      ? active(d).length
      : view === "review"
        ? Object.values(d.body.decisions).some((q) => !q.resolved)
        : d.body.relationship === "merchant",
  );
  $("#content").innerHTML =
    '<div class="cards">' +
    (list
      .map(
        (d) =>
          `<article class="card"><div class="row"><div><h2>${esc(d.name)}</h2><span class="meta">版本 ${d.version} · ${d.body.coverage.complete_context ? "相关文本窗口完整" : "资料覆盖有限，不自动创建新行动"}${d.body.paused ? " · 已暂停联系" : ""}${d.needs_update ? " · 新进展待整理" : ""}</span></div><button data-open="${esc(d.id)}" class="primary">查看档案</button></div><p class="reason">${esc(view === "today" ? active(d)[0][1].text : Object.values(d.body.notes)[0]?.text || "初步沟通")}</p></article>`,
      )
      .join("") ||
      '<div class="empty"><h2>当前没有可展示的结果</h2><p class="muted">在“试点与进度”选择一位联系人分析。无必要行动、身份未明确或覆盖不足时，不会强行创建待办。</p></div>') +
    "</div>";
}
async function pilot() {
  const current = view;
  try {
    const data = await api("candidates?page=" + candidatePage),
      runs = await api("runs");
    if (view !== current) return;
    $("#content").innerHTML =
      `<div class="card"><h2>选择一位真实联系人</h2><p class="muted">读取此人在授权私信与群聊中的相关文本。会调用 DeepSeek 并计入已有预算；先在原工作台设置模型和外发授权。单次最多3次请求。</p><label for="contact">联系人（来源身份，不代表已确认为商家）</label><select id="contact">${data.items.map((c) => `<option value="${esc(c.source_id)}">${esc(c.name)} · ${esc(c.source_id)}</option>`).join("")}</select><div class="toolbar spaced"><button id="prev" ${candidatePage === 1 ? "disabled" : ""}>上一页</button><span>第 ${candidatePage} 页 · ${data.total} 位来源联系人</span><button id="next" ${!data.has_more ? "disabled" : ""}>下一页</button></div><button class="primary" id="analyze" ${busy || !data.items.length ? "disabled" : ""}>${busy ? "正在分析，请稍候…" : "分析此联系人"}</button><p class="meta">不会启动全库重建。图片尚未识别，历史窗口过长时将标记资料不足。</p></div><section class="card spaced"><h2>最近运行</h2>${runs.map((r) => `<p>${esc(r.created_at)} · ${esc(r.status)} · ${r.calls} 次请求</p>${r.error ? `<p class="error">${esc(r.error)}</p>` : ""}`).join("") || "<p>尚未运行试点分析。</p>"}</section>`;
  } catch (e) {
    $("#status").textContent = e.message;
  }
}
function evidence(refs, d) {
  const ids = new Set(refs.map((r) => r.id));
  return `<details><summary>查看来源</summary>${d.evidence
    .filter((m) => ids.has(m.id))
    .map(
      (m) =>
        `<div class="evidence"><p class="meta">${esc(m.conversation)} · ${esc(m.event_time)}</p><p>${esc(m.text)}</p></div>`,
    )
    .join("")}</details>`;
}
function openDetail(id) {
  selected = documents.find((d) => d.id === id);
  const d = selected;
  focusBefore = document.activeElement;
  $("#detail-title").textContent = d.name;
  $("#detail-status").textContent = "";
  $("#detail").innerHTML =
    `<section class="section"><h3>微信定位</h3><p>${esc(d.location.remark || d.location.nickname || "姓名待同步")}</p><p class="meta">${d.location.conversations.map((c) => esc(c.title)).join(" / ")}</p><button data-operation="pause" data-value="${!d.body.paused}">${d.body.paused ? "恢复联系建议" : "暂停联系建议"}</button></section><section class="section"><h3>初步沟通与资料</h3>${
      Object.values(d.body.notes)
        .map((n) => `<p>${esc(n.text)}</p>${evidence(n.evidence, d)}`)
        .join("") || "<p>暂无确定资料。</p>"
    }</section><section class="section"><h3>备货批次</h3>${
      Object.values(d.body.batches)
        .map(
          (b) =>
            `<p>${esc(b.text)} · ${stages[b.stage]}</p>${evidence(b.evidence, d)}`,
        )
        .join("") || "<p>尚无具体批次。</p>"
    }</section><section class="section"><h3>下一步</h3>${
      Object.entries(d.body.actions)
        .map(
          ([id, a]) =>
            `<p>${esc(a.text)} · ${esc(a.state)}</p><p class="meta">${esc(a.reason)} ${esc(a.due_date || "未约定日期")}</p>${evidence(a.evidence, d)}${["open", "waiting"].includes(a.state) ? `<button data-operation="action" data-target="${id}" data-value="done">标记已处理</button>` : ""}`,
        )
        .join("") || "<p>当前无需行动。</p>"
    }</section><section class="section"><h3>关键确认</h3>${
      Object.entries(d.body.decisions)
        .filter(([, q]) => !q.resolved)
        .map(
          ([id, q]) =>
            `<label>${esc(q.text)}${id === "role" ? `<select id="decision-${id}"><option value="merchant">商家</option><option value="non_target">非目标客户（同事／服务商等）</option><option value="candidate">暂不能确定</option></select>` : `<input id="decision-${id}" maxlength="500" placeholder="填写明确判断；保存为人工约束">`}</label>${evidence(q.evidence, d)}<button data-operation="decision" data-target="${id}">保存判断</button>`,
        )
        .join("") || "<p>暂无待确认。</p>"
    }</section>`;
  $("dialog").showModal();
}
function close() {
  $("dialog").close();
  if (focusBefore?.isConnected) focusBefore.focus();
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
    if (b.dataset.view) {
      view = b.dataset.view;
      render();
    }
    if (b.dataset.open) openDetail(b.dataset.open);
    if (b.id === "close") close();
    if (b.id === "prev" || b.id === "next") {
      candidatePage += b.id === "next" ? 1 : -1;
      pilot();
    }
    if (b.id === "analyze") {
      if (busy) return;
      const source = $("#contact").value;
      busy = true;
      b.disabled = true;
      b.textContent = "正在分析，请稍候…";
      $("#status").textContent = "正在检索并整理该联系人…";
      try {
        await api("analyze", { source_id: source });
        await refresh();
        $("#status").textContent =
          "分析完成。可在客户或待确认中查看；无业务依据时不会创建客户。";
      } finally {
        busy = false;
        if (view === "pilot") pilot();
      }
    }
    if (b.dataset.operation) {
      b.disabled = true;
      const value =
        b.dataset.operation === "pause"
          ? b.dataset.value === "true"
          : b.dataset.operation === "decision"
            ? $("#decision-" + b.dataset.target).value
            : b.dataset.value;
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: b.dataset.operation,
        target: b.dataset.target,
        value,
      });
      close();
      await refresh();
    }
  } catch (e) {
    ($("dialog").open ? $("#detail-status") : $("#status")).textContent =
      e.message;
    b.disabled = false;
  }
});
$("dialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  close();
});
refresh().catch((e) => ($("#status").textContent = e.message));
