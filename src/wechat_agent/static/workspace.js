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
  candidatePage = 1,
  candidateQuery = "",
  candidateSource = "",
  candidateRequest = 0;
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
        ? Object.values(d.body.decisions).some((q) => !q.resolved) ||
          Object.values(d.body.actions).some((a) => a.state === "proposed")
        : d.body.relationship === "merchant",
  );
  $("#content").innerHTML =
    '<div class="cards">' +
    (list
      .map(
        (d) =>
          `<article class="card"><div class="row"><div><h2>${esc(d.name)}</h2><span class="meta">版本 ${d.version} · ${d.body.coverage.complete_context ? "相关文本窗口完整" : "资料覆盖有限，行动建议需确认"}${d.body.paused ? " · 已暂停联系" : ""}${d.needs_update ? " · 新进展待整理" : ""}</span></div><button data-open="${esc(d.id)}" class="primary">查看档案</button></div><p class="reason">${esc(view === "today" ? active(d)[0][1].text : Object.values(d.body.notes)[0]?.text || "初步沟通")}</p></article>`,
      )
      .join("") ||
      '<div class="empty"><h2>当前没有可展示的结果</h2><p class="muted">在“试点与进度”选择一位联系人分析。无必要行动、身份未明确或覆盖不足时，不会强行创建待办。</p></div>') +
    "</div>";
}
const candidateBlocks = {
  analysis_disabled:
    "尚未开启文本分析授权。前往设置确认范围和预算后，返回刷新联系人。",
  key_missing: "尚未配置 DeepSeek key。前往设置保存后，返回刷新联系人。",
  source_unauthorized:
    "此联系人的来源会话尚未授权外发。前往会话范围检查分析授权。",
  no_text:
    "此联系人暂无已授权的完整文本，现有图片或不完整记录不能用于本次分析。",
};
const emptyCandidates = {
  account_unbound: [
    "尚未绑定工作微信",
    "请在原工作台设置中检测连接并确认工作账号。",
    "settings",
  ],
  no_archive: [
    "当前账号尚无归档消息",
    "请在原工作台设置中检查 wx-cli 与采集状态；已有归档时，请核对绑定账号和启动时的数据目录，无需重复导入。",
    "settings",
  ],
  scope_excluded: [
    "暂无正常跟进会话",
    "当前归档会话未进入跟进范围，或已加入免跟进白名单。只恢复确实需要跟进的会话即可。",
    "scope",
  ],
  no_identity: [
    "暂未找到可选联系人",
    "正常跟进范围内尚无可识别的私信对象或群消息发送者，或人物已加入白名单。请检查人物白名单及源端身份信息；无需先让模型分析。",
    "scope",
  ],
};
function updateCandidateButton() {
  const option = $("#contact")?.selectedOptions[0];
  const reason = option?.dataset.blocked;
  $("#analyze").disabled = busy || !option || !!reason;
  $("#candidate-readiness").textContent = reason
    ? candidateBlocks[reason]
    : option
      ? "可开始分析。只读取此人在已授权范围内的相关文本。"
      : "";
  candidateSource = option?.value || "";
}
async function pilot() {
  const ticket = ++candidateRequest;
  try {
    const params = new URLSearchParams({
      page: candidatePage,
      q: candidateQuery,
    });
    const [data, runs] = await Promise.all([
      api("candidates?" + params),
      api("runs"),
    ]);
    if (view !== "pilot" || ticket !== candidateRequest) return;
    candidatePage = data.page;
    const d = data.diagnostics;
    const empty = emptyCandidates[d.empty_reason];
    const search = `<form id="candidate-search" class="toolbar spaced"><label class="candidate-search">搜索联系人<input name="q" maxlength="100" value="${esc(candidateQuery)}" placeholder="备注、昵称或微信 ID"></label><button type="submit">搜索</button></form>`;
    const picker = data.items.length
      ? `<label for="contact">联系人（来源身份，不代表已确认为商家）</label><select id="contact" aria-describedby="candidate-readiness">${data.items.map((c) => `<option value="${esc(c.source_id)}" data-blocked="${esc(c.blocked_reason || "")}" ${c.source_id === candidateSource ? "selected" : ""}>${esc(c.name)} · ${esc(c.source_id)}${c.blocked_reason ? " · 待就绪" : ""}</option>`).join("")}</select><div class="toolbar spaced"><button id="prev" ${candidatePage === 1 ? "disabled" : ""}>上一页</button><span>第 ${candidatePage} 页 · ${data.total} 位来源联系人 · 每页最多 50 位</span><button id="next" ${!data.has_more ? "disabled" : ""}>下一页</button></div><p id="candidate-readiness" class="muted" role="status"></p><button class="primary spaced" id="analyze" disabled>${busy ? "正在分析，请稍候…" : "分析此联系人"}</button>`
      : `<div class="candidate-empty spaced" role="status"><h3>${empty ? empty[0] : "没有匹配的联系人"}</h3><p>${empty ? empty[1] : "请尝试其他备注、昵称或微信 ID，或清空搜索后重试。"}</p>${empty ? `<a href="/?page=${empty[2]}">${empty[2] === "settings" ? "前往连接与模型设置" : "检查会话范围与人物白名单"} →</a>` : '<button id="clear-candidate-search">清空搜索</button>'}</div>`;
    $("#content").innerHTML =
      `<div class="card"><div class="toolbar"><h2>选择一位真实联系人</h2><button id="refresh-candidates">刷新联系人</button></div><p class="muted">联系人从本机归档读取，查看列表不调用模型。点击分析才会调用 DeepSeek，计入已有预算，单次最多 3 次请求。</p><p class="meta">当前账号已归档 ${d.archived_messages} 条消息 · 正常跟进 ${d.scope_conversations} 个会话 · 可识别 ${d.contacts} 位联系人</p>${search}${picker}<div class="toolbar spaced"><a href="/?page=settings">模型与分析授权设置 →</a><a href="/?page=scope">会话范围与白名单 →</a></div><p class="meta">修改设置后返回刷新。不会启动全库重建。图片尚未识别，历史窗口过长时将标记资料不足。</p></div><section class="card spaced"><h2>最近运行</h2>${runs.map((r) => `<p>${esc(r.created_at)} · ${esc(r.status)} · ${r.calls} 次请求</p>${r.error ? `<p class="error">${esc(r.error)}</p>` : ""}`).join("") || "<p>尚未运行试点分析。</p>"}</section>`;
    if (data.items.length) updateCandidateButton();
  } catch (e) {
    if (view === "pilot" && ticket === candidateRequest)
      $("#status").textContent = e.message;
  }
}
document.addEventListener("change", (e) => {
  if (e.target.id === "contact") updateCandidateButton();
});
document.addEventListener("submit", (e) => {
  if (e.target.id !== "candidate-search") return;
  e.preventDefault();
  candidateQuery = new FormData(e.target).get("q").trim();
  candidatePage = 1;
  pilot();
});

function evidence(refs, d) {
  const ids = new Set(refs.map((r) => r.id));
  return `<details><summary>查看来源</summary>${d.evidence
    .filter((m) => ids.has(m.id))
    .map(
      (m) =>
        `<div class="evidence"><p class="meta">${esc(m.conversation)} · ${esc(new Date(m.event_time).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }))}</p><p>${esc(m.text)}</p></div>`,
    )
    .join("")}</details>`;
}
function correction(section, id, item) {
  return `<details><summary>纠正这条内容</summary><label>核对来源后的表述<input maxlength="500" id="correct-${id}" value="${esc(item.text)}"></label><button data-operation="correct" data-target="${section}:${id}" data-input="correct-${id}">保存纠正</button></details>`;
}
function openDetail(id) {
  selected = documents.find((d) => d.id === id);
  const d = selected;
  focusBefore = document.activeElement;
  $("#detail-title").textContent = d.name;
  $("#detail-status").textContent = "";
  $("#detail").innerHTML =
    `<section class="section"><h3>微信定位</h3><p>${esc(d.location.remark || d.location.nickname || "姓名待同步")}</p><p class="meta">${d.location.conversations.map((c) => esc(c.title)).join(" / ")}</p><button data-operation="pause" data-value="${!d.body.paused}">${d.body.paused ? "恢复联系建议" : "暂停联系建议"}</button></section><section class="section"><h3>初步沟通与资料</h3>${
      Object.entries(d.body.notes)
        .map(
          ([id, n]) =>
            `<article class="insight-card"><p>${esc(n.text)}</p>${evidence(n.evidence, d)}${correction("notes", id, n)}</article>`,
        )
        .join("") || "<p>暂无确定资料。</p>"
    }</section><section class="section"><h3>备货批次</h3>${
      Object.entries(d.body.batches)
        .map(
          ([id, b]) =>
            `<article class="insight-card"><span class="meta">${stages[b.stage]}</span><p>${esc(b.text)}</p>${evidence(b.evidence, d)}${correction("batches", id, b)}</article>`,
        )
        .join("") || "<p>尚无具体批次。</p>"
    }</section><section class="section"><h3>下一步</h3>${
      Object.entries(d.body.actions)
        .map(
          ([id, a]) =>
            `<article class="insight-card"><p>${esc(a.text)} · ${esc({ open: "待处理", waiting: "等待回复", done: "已完成", cancelled: "已取消", proposed: "待确认建议", historical_unresolved: "历史待核实" }[a.state] || a.state)}</p><p class="meta">${esc(a.reason)} ${esc(a.due_date || "未约定日期")}</p>${evidence(a.evidence, d)}${a.state === "proposed" ? `<p class="meta">来源覆盖或责任归属尚需确认，请核对原文。</p><button data-operation="confirm_action" data-target="${id}" data-value="true">确认由我跟进</button>` : ""}${["open", "waiting"].includes(a.state) ? `<button data-operation="action" data-target="${id}" data-value="done">标记已处理</button><button data-operation="action" data-target="${id}" data-value="waiting">等待回复</button><label>下次联系日期<input type="date" id="schedule-${id}"></label><button data-operation="schedule" data-target="${id}">保存日期</button>` : ""}</article>`,
        )
        .join("") ||
      `<p>${d.body.coverage.complete_context ? "当前文本未识别出明确的未完成行动。" : "上下文含未读媒体或历史截断，不能判定无需行动。请核对来源后重新分析。"}</p>`
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
    if (b.id === "refresh-candidates" || b.id === "clear-candidate-search") {
      if (b.id === "clear-candidate-search") candidateQuery = "";
      candidatePage = 1;
      b.disabled = true;
      await pilot();
      if (b.isConnected) b.disabled = false;
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
        b.dataset.operation === "correct"
          ? $("#" + b.dataset.input).value
          : ["pause", "confirm_action"].includes(b.dataset.operation)
            ? b.dataset.value === "true"
            : b.dataset.operation === "schedule"
              ? $("#schedule-" + b.dataset.target).value
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
