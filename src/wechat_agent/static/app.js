"use strict";
const $ = (s) => document.querySelector(s),
  esc = (v) =>
    String(v ?? "").replace(
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
let state = {},
  currentPage = "today",
  actionFilter = "today",
  customerPage = 1,
  archivePage = 1,
  archiveHasMore = false,
  filePreview = null,
  messageRows = [],
  messageMode = "focus",
  messageContext = null,
  imageURLs = [];
const statusNames = {
  open: "待推进",
  waiting_external: "等待回复",
  snoozed: "已改期",
  done: "已完成",
  cancelled: "不再推进",
  historical_unresolved: "历史未决",
};
const fields = {
  company: "公司／店铺",
  market: "目标市场",
  cargo: "货型／品类",
  volume: "货量",
  timing: "出货窗口",
  concern: "关注与顾虑",
  preference: "偏好",
  summary: "近期摘要",
};
async function api(path, body) {
  const r = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": $('meta[name="csrf-token"]').content,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw Error(data.error || data.detail || "操作未完成");
  return data;
}
function notice(message, error = false) {
  $("#notice").textContent = message;
  $("#notice").className = "notice" + (error ? " error" : "");
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => $("#notice").classList.add("hidden"), 6000);
}
const safe = (fn) => async (e) => {
  try {
    await fn(e);
  } catch (err) {
    notice(err.message, true);
  }
};
function empty(title, text, button = "") {
  return `<div class="empty"><div class="empty-icon">◌</div><h2>${esc(title)}</h2><p>${esc(text)}</p>${button}</div>`;
}
function dateLabel(value) {
  if (!value) return "时间待定";
  const d = new Date(value);
  return Number.isNaN(d.valueOf())
    ? value
    : d.toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}
function showDetail(title, html) {
  imageURLs.forEach(URL.revokeObjectURL);
  imageURLs = [];
  $("#detail-title").textContent = title;
  $("#detail-body").innerHTML = html;
  if (!$("#detail").open) $("#detail").showModal();
}
function go(page) {
  currentPage = page;
  document
    .querySelectorAll(".page")
    .forEach((el) => el.classList.toggle("hidden", el.id !== "page-" + page));
  document
    .querySelectorAll("[data-page]")
    .forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  document.title =
    "半托管欧区备货用户助手 · " +
    {
      today: "今日跟进",
      customers: "客户",
      scope: "会话范围",
      reviews: "待确认",
      settings: "设置",
      analysis: "分析概览",
    }[page];
  if (page === "customers")
    loadCustomers().catch((e) => notice(e.message, true));
  if (page === "reviews") loadReviews().catch((e) => notice(e.message, true));
  if (page === "settings") { renderSettings(); loadSources().catch((e) => notice(e.message, true)); loadMonitor(); }
  if (page === "scope") { loadSources().catch(e=>notice(e.message,true)); loadPeople().catch(e=>notice(e.message,true)); }
  if (page === "analysis") loadAnalysis().catch((e) => notice(e.message, true));
}
function renderToday() {
  $("#today-count").textContent = state.due_count || 0;
  $("#waiting-count").textContent = state.waiting_count || 0;
  $("#customer-count").textContent =
    `${state.customers_count || 0} 位已识别客户`;
  const policy = state.policy;
  let banner = "";
  if (!state.account_id)
    banner =
      "<strong>先连接你的工作微信</strong><p>连接后，助手会整理私信与群聊，无需先建客户。</p>";
  else if (!policy?.enabled)
    banner =
      "<strong>聊天已归档，开启自动整理</strong><p>确认 DeepSeek 分析范围后，自动建立客户档案和跟进计划。</p>";
  else if (!state.source_scope?.selected)
    banner = "<strong>当前没有可跟进会话</strong><p>检查免跟进白名单或等待新会话；聊天继续归档。</p>";
  else if (!state.key_configured)
    banner =
      "<strong>还需要连接 DeepSeek</strong><p>消息采集继续，配置 API key 后才能分析。</p>";
  $("#setup-banner").classList.toggle("hidden", !banner);
  $("#setup-banner").innerHTML = banner
    ? `<div>${banner}</div><button class="primary" data-go="settings">前往设置 →</button>`
    : "";
  const jobs = Object.fromEntries(
    (state.jobs || []).map((j) => [j.status, j.n]),
  );
  $("#progress").classList.toggle("hidden", !state.messages);
  $("#progress").textContent =
    `已归档 ${state.messages || 0} 条 · 近15天优先分析 · 已产出 ${state.customers_count || 0} 位客户` +
    (jobs.blocked_budget ? " · 查看用量与预算原因" : "") +
    " · 媒体待识别";
  let actions =
    actionFilter === "today"
      ? state.actions || []
      : (state.all_actions || []).filter((a) =>
          actionFilter === "waiting" ? a.state === "waiting_external" : true,
        );
  $("#action-list").innerHTML = actions.length
    ? actions
        .map(
          (a) =>
            `<article class="action-card"><div class="avatar">${esc(a.customer_name.slice(0, 1))}</div><div><div class="card-heading"><h3>${esc(a.customer_name)}</h3><span class="tag ${a.due_date < state.today && a.state === "open" ? "amber" : ""}">${esc(statusNames[a.state] || a.state)}</span></div><div class="card-meta">${esc(a.opportunity || "客户跟进")} · ${esc(a.due_date || "时间待定")}${a.date_kind === "suggested" ? "（建议）" : ""} · 联系 ${esc(a.contact_name || a.customer_name)}</div><h2>${esc(a.summary)}</h2><div class="reason">为什么：${esc(a.reason)}${!a.source_eligible ? " · 来源已免跟进或暂停分析，保留历史记录" : !a.evidence_valid ? " · 原始依据已变化，等待重算" : ""}</div><div class="card-actions"><button data-evidence="${esc(a.id)}">查看依据</button><button data-draft="${esc(a.id)}" ${a.do_not_contact || !a.source_eligible || !a.evidence_valid || ["done", "cancelled", "historical_unresolved"].includes(a.state) ? "disabled" : ""}>查看话术</button><button data-result="${esc(a.id)}">记录结果</button><button data-postpone="${esc(a.id)}">改期</button><button class="quiet" data-customer="${esc(a.customer_id)}">客户档案 ↗</button></div></div></article>`,
        )
        .join("")
    : empty(
        actionFilter === "today"
          ? "今天暂无到期行动"
          : actionFilter === "waiting"
            ? "暂无等待回复的事项"
            : "还没有跟进计划",
        policy?.enabled
          ? "助手会根据新的需求、约定与回复更新这里。历史整理尚未完成时，当前档案为初步结果。"
          : "开启自动整理后，有明确需求的客户会出现在这里。",
      );
}
function renderSettings() {
  $("#account-status").textContent = state.account_id
    ? "已绑定：" +
      (state.account_name || state.account_id) +
      (state.account_name && state.account_name !== state.account_id
        ? "（" + state.account_id + "）"
        : "")
    : "尚未确认工作账号";
  $("#key-status").textContent = state.key_configured
    ? "已检测到本机 API key；实际可用性以请求结果为准。"
    : "尚未配置 API key。";
  $("#key-form").classList.toggle("hidden", !!state.key_configured);
  $("#change-key").classList.toggle("hidden", !state.key_configured);
  $("#policy-form [name=daily_budget]").value =
    state.policy?.daily_budget || 100000;
  $("#policy-form [name=consent]").checked = !!state.policy?.enabled;
  $("#diagnostics").innerHTML =
    (state.runtime || [])
      .map(
        (r) =>
          `<p>${esc(r.name)} · ${esc(r.status)} · ${esc(dateLabel(r.updated_at))}</p>`,
      )
      .join("") +
    "<p>后台：" +
    (state.background
      ? "已随工作台启动"
      : "未启用，请使用 wechat-agent start") +
    "</p>";
}
async function load() {
  state = await api("/api/crm");
  $("#review-count").textContent = state.reviews_count || "";
  const collector = state.runtime?.find((r) => r.name === "collector");
  $("#sync-status").textContent = collector
    ? `采集 ${collector.status === "running" ? "运行中" : collector.status} · ${dateLabel(collector.updated_at)}`
    : "本地归档 " + (state.messages || 0) + " 条";
  if (currentPage === "today") renderToday();
  if (currentPage === "analysis") await loadAnalysis();
}
async function loadCustomers() {
  const q = $("#customer-search [name=q]").value;
  const rows = await api(
    `/api/crm/customers?q=${encodeURIComponent(q)}&page=${customerPage}`,
  );
  $("#customer-list").innerHTML = rows.length
    ? rows
        .map(
          (c) =>
            `<button class="customer-card" data-customer="${esc(c.id)}"><strong>${esc(c.name)}</strong><p>${esc(c.summary || "档案由聊天证据自动整理；点开查看需求和沟通重点。")}</p>${c.do_not_contact ? '<span class="tag amber">暂停联系</span>' : ""}</button>`,
        )
        .join("")
    : empty(
        "客户会从聊天中出现",
        "有足够的商家身份与需求依据时，助手会自动建档，无需填写商家表。",
      );
  $("#customers-page").textContent = customerPage;
  $("#customers-prev").disabled = customerPage === 1;
  $("#customers-next").disabled = rows.length < 50;
}
function messageHTML(rows) {
  return rows
    .map(
      (m) =>
        `<article class="message ${m.value === "noise" ? "noise" : ""}" id="message-${esc(m.id)}"><div class="meta">${esc(m.conversation_title || "来源消息")} · ${esc(dateLabel(m.event_time))} · ${m.direction === "outgoing" ? "我方" : m.sender_id === "unknown" ? "身份待确认" : "对方"}${m.revision ? " · 修订 " + m.revision : ""}</div>${m.evidence_label ? '<div class="evidence-label">档案／行动依据</div>' : ""}<p>${esc(m.text)}</p>${m.type === "3" || m.type === "image" ? `<button data-image="${esc(m.id)}">读取本机图片</button><div id="image-${esc(m.id)}"></div>` : ""}</article>`,
    )
    .join("");
}
function renderMessageBlock() {
  const rows = messageRows.filter(
    (m) => messageMode === "all" || m.value !== "noise",
  );
  $("#message-items").innerHTML = rows.length
    ? messageHTML(rows)
    : '<p class="hint">这一页只有简短确认／寒暄；可切换全部，或继续翻页。</p>';
  $("#message-filter").textContent =
    messageMode === "focus" ? "查看全部消息" : "只看重点";
  $("#message-filter-note").textContent =
    messageMode === "focus"
      ? "已折叠空文本及简短寒暄／确认；保留内容并不代表已经被判定有商业价值。"
      : "全部原文；原始记录不会被过滤删除。";
}
function messageSection(rows) {
  messageRows = rows;
  return '<div class="button-row"><button id="message-filter">查看全部消息</button></div><p class="hint" id="message-filter-note"></p><div id="message-items"></div>';
}
async function showCustomer(id) {
  const d = await api("/api/crm/customers/" + encodeURIComponent(id));
  messageMode = "focus";
  const valid = d.facts.filter((f) => f.evidence_valid);
  let seen = new Set();
  const facts = valid.filter((f) => {
    if (
      ["company", "summary", "market", "cargo", "volume", "timing"].includes(
        f.field,
      )
    ) {
      if (seen.has(f.field)) return false;
      seen.add(f.field);
    }
    return true;
  });
  showDetail(
    d.customer.name,
    `${locationHTML(d.location)}<div class="button-row"><button data-dnc="${esc(id)}" data-current="${d.customer.do_not_contact}">${d.customer.do_not_contact ? "恢复联系建议" : "暂停联系此客户"}</button></div><h2>客户近况</h2>${facts.length ? facts.map((f) => `<div class="fact"><strong>${esc(fields[f.field] || f.field)} · ${f.locked ? "人工确认" : "对话提取"}</strong><p>${esc(f.value)}</p><details><summary class="hint">查看来源／纠正</summary><button data-correct-fact="${esc(f.id)}" data-value="${esc(f.value)}" data-owner="${esc(id)}">纠正此项</button>${messageHTML(f.sources.map((m) => ({ ...m, evidence_label: true })))}</details></div>`).join("") : '<p class="hint">尚无已验证的详细需求，未知字段不会要求你逐一补填。</p>'}<h2>当前机会与计划</h2>${d.plans.map((p) => `<p>${esc(p.name)} <span class="tag">${esc(p.stage)}</span></p>`).join("") || '<p class="hint">尚未识别具体业务机会。</p>'}<h2>沟通重点</h2><p class="hint">最近 300 条可见私信与此联系人的群发言；完整会话在设置中的消息档案查看。</p>${messageSection(d.messages)}`,
  );
  renderMessageBlock();
}
async function showEvidence(id) {
  const d = await api("/api/crm/actions/" + id + "/evidence");
  showDetail(
    "为什么要跟进",
    `<h2>${esc(d.action.summary)}</h2><p>${esc(d.action.reason)}</p>${d.messages.length ? messageHTML(d.messages.map((m) => ({ ...m, evidence_label: true }))) : "<p>来源已修订，等待重新分析；当前不使用旧依据起草话术。</p>"}`,
  );
}
async function loadReviews() {
  const rows = await api("/api/crm/reviews");
  $("#review-list").innerHTML = rows.length
    ? rows
        .map(
          (r) =>
            `<article class="review-card"><h2>${esc(r.question)}</h2><details><summary>查看判断依据</summary>${messageHTML(r.sources)}</details><form data-review="${esc(r.id)}"><label>确认或补充一句话<textarea name="resolution" placeholder="例如：这位联系人是服务商，不是商家" maxlength="1000" required></textarea></label><button class="primary">保存判断</button></form></article>`,
        )
        .join("")
    : empty(
        "暂时没有需要你确认的事",
        "常规建档与待办自动生效，有影响业务的歧义时才会出现。",
      );
}
async function loadArchive() {
  const d = await api("/api/archive/conversations?page=" + archivePage);
  archiveHasMore = d.has_more;
  $("#archive-list").innerHTML =
    d.items
      .map(
        (c) =>
          `<button class="archive-entry" data-conversation="${esc(c.id)}">${esc(c.title)} <span class="hint">${c.kind === "group" ? "群聊" : "私信"} · ${c.message_count} 条</span></button><button class="quiet" data-conversation-policy="${esc(c.id)}" data-enabled="${c.egress ? "false" : "true"}">${c.egress ? "暂停此会话分析" : "启用此会话分析"}</button>`,
      )
      .join("") || '<p class="hint">尚无可见归档会话。</p>';
  $("#archive-page").textContent = archivePage;
  $("#archive-prev").disabled = archivePage === 1;
  $("#archive-next").disabled = !archiveHasMore;
  const report = await api("/api/archive/status");
  $("#diagnostics").innerHTML =
    "<p>归档覆盖：" +
    esc(report.scope) +
    " · 隔离行 " +
    report.quarantined_rows +
    " · 缺口 " +
    report.issues.reduce((n, r) => n + r.count, 0) +
    "</p>" +
    (state.runtime || [])
      .map((r) => `<p>${esc(r.name)} · ${esc(r.status)}</p>`)
      .join("");
}
async function showConversation(id, page = 1) {
  const rows = await api("/api/messages/" + id + "?page=" + page);
  messageContext = { id, page };
  messageMode = "focus";
  const tagged = rows.map((m) => ({ ...m, value: m.value || "candidate" }));
  showDetail(
    "消息档案 · 第 " + page + " 页",
    messageSection(tagged) +
      `<div class="pagination"><button id="messages-newer" ${page === 1 ? "disabled" : ""}>更近消息</button><button id="messages-older" ${rows.length < 100 ? "disabled" : ""}>更早消息</button></div>`,
  );
  renderMessageBlock();
}
async function draft(id) {
  notice("正在根据消息依据起草…");
  const d = await api("/api/crm/actions/" + id + "/draft", {});
  showDetail(
    "跟进话术草稿",
    `<p class="hint">${esc(d.notice)}</p><textarea id="draft-text" class="draft">${esc(d.text)}</textarea><div class="button-row"><button id="copy-draft" class="primary">复制，去微信发送</button></div>`,
  );
}
function resultDialog(id, postpone = false) {
  const a = state.all_actions.find((x) => x.id === id);
  if (!a) return;
  showDetail(
    postpone ? "调整跟进日期" : "记录实际沟通结果",
    `<h2>${esc(a.summary)}</h2><form id="result-form" data-id="${esc(id)}" data-version="${a.version}">${postpone ? '<input name="due_date" type="date" required>' : '<label>结果<select name="state"><option value="waiting_external">已联系，等待回复</option><option value="done">此事项已解决</option><option value="cancelled">不再推进此事项</option><option value="open">仍需我方推进</option></select></label><label>补充结果<textarea name="note" maxlength="1000" placeholder="电话／线下沟通可在此补充一句"></textarea></label>'}<button class="primary">保存${postpone ? "日期" : "结果"}</button></form>`,
  );
}
document.addEventListener(
  "click",
  safe(async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const d = b.dataset;
    if (d.copyDiagnostics) {
      const result = await api("/api/analysis/progress");
      await navigator.clipboard.writeText(
        JSON.stringify(result.diagnostics, null, 2),
      );
      return notice("诊断已复制，不含聊天正文、账号ID或API key。");
    }
    if (d.usageDay) {
      selectedUsageDay = d.usageDay;
      return renderUsageTrend(usageDays);
    }
    if (d.page) return go(d.page);
    if (d.go) return go(d.go);
    if (d.filter) {
      actionFilter = d.filter;
      document
        .querySelectorAll("[data-filter]")
        .forEach((x) => x.classList.toggle("active", x === b));
      return renderToday();
    }
    if (d.customer) return showCustomer(d.customer);
    if (d.correctFact)
      return showDetail(
        "纠正客户信息",
        `<form id="fact-form" data-id="${esc(d.correctFact)}" data-owner="${esc(d.owner)}"><p class="hint">保存后标记为人工确认，后续分析不会自动覆盖。</p><textarea name="value" maxlength="500" required>${esc(d.value)}</textarea><button class="primary">保存纠正</button></form>`,
      );
    if (d.evidence) return showEvidence(d.evidence);
    if (d.draft) return draft(d.draft);
    if (d.result) return resultDialog(d.result);
    if (d.postpone) return resultDialog(d.postpone, true);
    if (d.conversation) return showConversation(d.conversation);
    if (d.conversationPolicy) {
      await api("/api/crm/conversations/" + d.conversationPolicy + "/policy", {
        enabled: d.enabled === "true",
      });
      await loadArchive();
      return notice("会话分析范围已更新，原始消息保留。");
    }
    if (d.dnc) {
      await api("/api/crm/customers/" + d.dnc + "/preferences", {
        do_not_contact: d.current !== "1",
      });
      await load();
      return showCustomer(d.dnc);
    }
    if (d.image) {
      b.disabled = true;
      const r = await fetch("/api/messages/" + d.image + "/image");
      if (!r.ok) {
        b.disabled = false;
        const failure = await r.json().catch(() => ({}));
        throw Error(
          failure.error || "图片读取失败：请检查本机媒体是否已下载及源服务。",
        );
      }
      const url = URL.createObjectURL(await r.blob());
      imageURLs.push(url);
      const target = document.getElementById("image-" + d.image);
      target.replaceChildren();
      const img = document.createElement("img");
      img.src = url;
      img.className = "archived-image";
      img.alt = "本机归档图片";
      target.append(img);
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent =
        r.headers.get("X-Wechat-Media-Quality") === "thumbnail"
          ? "当前为缩略图，未进行 OCR。"
          : "本机图片，未进行 OCR。";
      target.append(hint);
      return;
    }
    if (b.id === "message-filter") {
      messageMode = messageMode === "focus" ? "all" : "focus";
      renderMessageBlock();
    }
    if (b.id === "messages-newer")
      await showConversation(messageContext.id, messageContext.page - 1);
    if (b.id === "messages-older")
      await showConversation(messageContext.id, messageContext.page + 1);
    if (b.id === "copy-draft") {
      await navigator.clipboard.writeText($("#draft-text").value);
      notice("已复制；请到微信核对发送。");
    }
    if (b.id === "bind-account") {
      await api("/api/source/bind", { account_id: d.account });
      await load();
      renderSettings();
      notice("工作账号已确认，后台将发现会话并补齐历史。");
    }
  }),
);
document.addEventListener(
  "submit",
  safe(async (e) => {
    if (e.target.matches("[data-review]")) {
      e.preventDefault();
      await api("/api/crm/reviews/" + e.target.dataset.review, {
        resolution: new FormData(e.target).get("resolution"),
      });
      await load();
      await loadReviews();
      notice("已保存，将作为后续分析的纠正依据。");
    }
    if (e.target.id === "fact-form") {
      e.preventDefault();
      await api("/api/crm/facts/" + e.target.dataset.id, {
        value: new FormData(e.target).get("value"),
      });
      await showCustomer(e.target.dataset.owner);
      notice("已保存，后续分析保留你的判断。");
    }
    if (e.target.id === "budget-reconcile") {
      e.preventDefault();
      const form = new FormData(e.target);
      await api("/api/analysis/budget/reconcile", {
        confirmed_tokens: Number(form.get("confirmed_tokens")),
        confirm_billing: form.has("confirm_billing"),
      });
      await loadAnalysis();
      notice("预算已按你确认的账单校正，原始请求记录保留。");
    }
    if (e.target.id === "result-form") {
      e.preventDefault();
      const f = new FormData(e.target);
      await api("/api/crm/actions/" + e.target.dataset.id + "/transition", {
        version: Number(e.target.dataset.version),
        state: f.has("due_date") ? "snoozed" : f.get("state"),
        due_date: f.get("due_date") || null,
        note: f.get("note") || "",
      });
      $("#detail").close();
      await load();
      notice("结果已记录。");
    }
  }),
);
$("#refresh").onclick = safe(async () => {
  await load();
  if (currentPage === "settings") { renderSettings(); loadMonitor(); }
  if (currentPage === "scope") { await loadSources(); await loadPeople(); }
  if (currentPage === "customers") await loadCustomers();
  if (currentPage === "reviews") await loadReviews();
  notice("已刷新。");
});
$("#close-detail").onclick = () => $("#detail").close();
$("#detail").addEventListener("close", () => {
  imageURLs.forEach(URL.revokeObjectURL);
  imageURLs = [];
});
$("#customer-search").onsubmit = safe(async (e) => {
  e.preventDefault();
  customerPage = 1;
  await loadCustomers();
});
$("#customers-prev").onclick = safe(async () => {
  if (customerPage > 1) {
    customerPage--;
    await loadCustomers();
  }
});
$("#customers-next").onclick = safe(async () => {
  customerPage++;
  await loadCustomers();
});
$("#probe").onclick = safe(async () => {
  const d = await api("/api/source/probe", {});
  $("#source-result").innerHTML =
    `<div class="inset">检测到 ${esc(d.account_name || d.account_id)}<p class="hint">${esc(d.account_id)}</p><button id="bind-account" data-account="${esc(d.account_id)}">确认这是我的工作账号</button></div>`;
});
$("#change-key").onclick = () => $("#key-form").classList.toggle("hidden");
$("#key-form").onsubmit = safe(async (e) => {
  e.preventDefault();
  const key = new FormData(e.target).get("key");
  await api("/api/crm/credentials", { key });
  e.target.reset();
  await load();
  renderSettings();
  notice("API key 已保存到系统凭据存储。");
});
$("#policy-form").onsubmit = safe(async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  if (!f.has("consent"))
    throw Error("请确认工作账号及 DeepSeek 文本分析范围。");
  await api("/api/crm/configure", {
    enabled: true,
    daily_budget: Number(f.get("daily_budget")),
    include_new: state.policy?.include_new !== 0,
  });
  await load();
  go("today");
  notice("已开始自动整理，后台分批运行；无需手动建客户。");
});
$("#pause-analysis").onclick = safe(async () => {
  await api("/api/crm/configure", { enabled: false });
  await load();
  renderSettings();
  notice("已停止新的模型外发，消息归档继续。");
});
$("#file-import input").onchange = () => {
  filePreview = null;
  $("#write-file").disabled = true;
  $("#file-report").textContent = "";
};
$("#file-import").onsubmit = safe(async (e) => {
  e.preventDefault();
  const file = e.target.file.files[0];
  if (!file) throw Error("请选择文件");
  if (file.size > 1500000)
    throw Error("网页上限 1.5 MB，大文件请使用 CLI import。");
  filePreview = { filename: file.name, text: await file.text() };
  const d = await api("/api/imports/file", filePreview);
  $("#file-report").textContent =
    `有效 ${d.valid} 条 · 错误 ${d.rejected} 条 · ${d.conversations} 个会话` +
    (d.rejected ? "，请按标准格式修正文件。" : "");
  $("#write-file").disabled = d.rejected > 0 || !d.valid;
});
$("#write-file").onclick = safe(async () => {
  if (!filePreview) return;
  $("#write-file").disabled = true;
  const d = await api("/api/imports/file", { ...filePreview, write: true });
  $("#file-report").textContent =
    `已新增 ${d.inserted} 条，重复 ${d.duplicates} 条。`;
  filePreview = null;
  await load();
  notice("导入完成，已授权的数据将进入后台整理。");
});
$("#load-archive").onclick = safe(loadArchive);
$("#archive-prev").onclick = safe(async () => {
  if (archivePage > 1) {
    archivePage--;
    await loadArchive();
  }
});
$("#archive-next").onclick = safe(async () => {
  if (archiveHasMore) {
    archivePage++;
    await loadArchive();
  }
});
$("#retry").onclick = safe(async () => {
  await api("/api/crm/retry", {});
  await load();
  notice("已安排重试；预算不足时会继续等待。");
});
$("#date-label").textContent = new Date().toLocaleDateString("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "long",
});
load().catch((e) => notice(e.message, true));
setInterval(() => load().catch(() => {}), 15000);

let analysisEnabled = false;
let analysisPage = 1,
  analysisHasMore = false,
  analysisLoading = false;
const queueStatus = {
  queued: "已入队",
  running: "分析中",
  succeeded: "已完成",
  filtered_noise: "无需模型分析",
  deferred_recent: "近期待调度",
  deferred_history: "历史后台待调度",
  waiting_history_budget: "为近期保留预算",
  blocked_budget: "等待预算",
  blocked_credentials: "需检查API凭据",
  retry_wait: "等待重试",
  failed: "分析失败",
  blocked_context_limit: "单条上下文超限",
  superseded: "已由新分片替代",
  stale_input: "输入已变化",
};
const gateNames = {
  blocked_budget: "今日可用预算不足",
  blocked_credentials: "请检查 DeepSeek API key 或模型权限",
  rate_limited: "接口限流，等待后自动恢复",
  consecutive_errors: "连续请求未成功，已暂缓调用，避免继续消耗预算",
};
function metric(value, label, note = "") {
  return `<div class="analysis-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
}
async function loadAnalysis() {
  if (analysisLoading) return;
  analysisLoading = true;
  try {
    const d = await api("/api/analysis/progress"),
      b = d.budget,
      r = d.scope.recent,
      h = d.scope.history;
    analysisEnabled = d.enabled;
    $("#analysis-retry").textContent = d.enabled
      ? "恢复／重试分析"
      : "前往设置启用";
    $("#analysis-pause").disabled = !d.enabled;
    $("#analysis-status").innerHTML =
      `<span class="live-dot ${!d.enabled || d.gate ? "paused" : ""}"></span><div><strong>${!d.enabled ? "分析已暂停" : !d.source_scope?.selected ? "没有可分析的跟进会话，可在设置查看免跟进白名单" : d.gate ? esc(gateNames[d.gate.reason] || d.gate.reason) : r.pending ? "优先整理近 15 天的客户需求" : h.pending ? "近期已处理，历史按余量继续" : "本轮文本已处理，等待新消息"}</strong><p>${esc(d.account_name || "尚未连接工作账号")} · 更新于 ${esc(dateLabel(d.updated_at))}${d.gate ? " · 自动复查 " + esc(dateLabel(d.gate.until)) : ""}</p></div>`;
    if (d.gate && d.diagnostics?.recent_errors?.length) {
      const problem = d.diagnostics.recent_errors[0];
      $("#analysis-status").insertAdjacentHTML(
        "beforeend",
        `<div class="failure-reason"><strong>${esc(problem.title)} · ${esc(problem.code)}</strong><p>${esc(problem.action)}</p><button data-copy-diagnostics="true" class="quiet">复制诊断信息</button></div>`,
      );
    }
    $("#analysis-metrics").innerHTML =
      metric(
        d.messages.total || 0,
        "已归档消息",
        `正常跟进 ${d.source_scope?.selected || 0} / ${d.source_scope?.total || 0} 个会话 · 媒体 ${d.messages.media || 0} 条`,
      ) +
      metric(r.analyzed, "近期已分析", `近15天共 ${r.total} 条完整文本`) +
      metric(d.customers, "客户档案", "根据聊天证据自动整理") +
      metric(d.actions, "跟进事项", "包含历史状态，非全部今日待办");
    $("#analysis-scopes").innerHTML =
      "<h2>处理范围</h2>" +
      [
        ["近 15 天 · 优先", r],
        ["更早历史 · 后台", h],
      ]
        .map(
          ([label, v]) =>
            `<div class="scope-progress"><div class="row"><strong>${label}</strong><span>${v.percent}%</span></div><div class="progress-track"><i style="width:${Math.max(0, Math.min(100, v.percent))}%"></i></div><p>已分析 ${v.analyzed} · 简短无效文本 ${v.filtered} · 待处理 ${v.pending} / 共 ${v.total} 条</p></div>`,
        )
        .join("") +
      '<p class="hint">每轮最多8个近期分片；近期未完成前不推进历史。更早历史保留20%日预算给新增消息与话术。媒体单独计数，未纳入文本完成率。</p>';
    const used = Math.min(
      100,
      Math.round(((b.reported + b.uncertain) * 100) / b.limit),
    );
    $("#analysis-budget").innerHTML =
      `<h2>今日预算 <small>${esc(b.day)} · 北京时间</small></h2><div class="budget-number">${Number(b.reported).toLocaleString()} <span>/ ${Number(b.limit).toLocaleString()} token</span></div><div class="progress-track"><i style="width:${used}%"></i></div><div class="budget-breakdown"><span>已返回／已核对用量 <b>${b.reported}</b></span><span>未确认预留 <b>${b.uncertain}</b></span><span>剩余可调度 <b>${b.remaining}</b></span><span>请求记录 <b>${b.calls}</b></span></div><p class="hint">预留是估算，并非实际扣费；响应后以API用量替换。超时等未确认请求暂保留额度，明确拒绝或连接未建立的请求不占用预算。</p><button data-go="settings" class="quiet">调整预算 →</button>${b.uncertain ? '<details><summary class="hint">未确认预留与账单不一致？</summary><p class="hint">仅在核对 DeepSeek 今日账单后填写总 token 用量。这只校正本机预算，不修改账单；原始请求记录保留。</p><form id="budget-reconcile"><label>今日已确认总 token<input name="confirmed_tokens" type="number" min="0" max="100000000" required></label><label class="checkbox"><input name="confirm_billing" type="checkbox" required>已核对今日账单，包含截至现在的全部请求</label><button>按账单校正并恢复</button></form></details>' : ""}`;
    renderUsageTrend(d.daily_usage);
    $("#analysis-output").innerHTML =
      `<div class="budget-breakdown"><span>关键确认 <b>${d.reviews}</b></span><span>运行中 <b>${d.queue.running || 0}</b></span><span>待调度／入队 <b>${(d.queue.deferred_recent || 0) + (d.queue.deferred_history || 0) + (d.queue.queued || 0)}</b></span></div>` +
      d.runtime
        .map(
          (v) =>
            `<p class="hint">${esc(v.name)} · ${esc(v.status)} · ${esc(dateLabel(v.updated_at))}</p>`,
        )
        .join("") +
      d.failures
        .map(
          (v) =>
            `<p class="error-note">${esc(v.error || "等待处理")} · ${v.n} 个分片</p>`,
        )
        .join("") +
      '<p class="hint">重试只针对未完成分片；成功结果和原始消息保留。队列不显示原始聊天正文。</p>';
    await loadAnalysisJobs();
  } finally {
    analysisLoading = false;
  }
}
async function loadAnalysisJobs() {
  const scope = $("#analysis-scope").value,
    status = $("#analysis-filter").value;
  const d = await api(
    `/api/analysis/jobs?scope=${scope}&status=${status}&page=${analysisPage}`,
  );
  analysisHasMore = d.has_more;
  $("#analysis-jobs").innerHTML = d.items.length
    ? d.items
        .map(
          (j) =>
            `<div class="queue-item"><div><strong>${esc(j.conversation_title)}</strong><p>${j.scope === "recent" ? "近15天" : "更早历史"} · ${j.message_count} 条 · ${esc(dateLabel(j.range_start))} — ${esc(dateLabel(j.range_end))}</p></div><div><span class="tag ${j.status === "failed" || j.error ? "amber" : ""}">${esc(queueStatus[j.status] || j.status)}</span><p>尝试 ${j.attempts} 次 · 已报告 ${j.reported_tokens || 0} token${j.uncertain_tokens ? " · 未确认 " + j.uncertain_tokens : ""}</p>${j.error ? `<small>${esc(j.error)}</small>` : ""}</div></div>`,
        )
        .join("")
    : empty("此范围暂无分片", "新消息按需分批入队；无需重新导入聊天记录。");
  $("#analysis-page").textContent = `第 ${analysisPage} 页 · ${d.total} 个分片`;
  $("#analysis-prev").disabled = analysisPage === 1;
  $("#analysis-next").disabled = !d.has_more;
}
$("#analysis-refresh").onclick = safe(loadAnalysis);
$("#analysis-retry").onclick = safe(async () => {
  if (!analysisEnabled) return go("settings");
  await api("/api/crm/retry", {});
  await loadAnalysis();
  notice("已恢复近期优先调度；预算仍按当前额度控制。");
});
$("#analysis-pause").onclick = safe(async () => {
  await api("/api/crm/configure", { enabled: false });
  await load();
  notice("分析已暂停，采集继续。");
});
for (const id of ["analysis-scope", "analysis-filter"])
  $("#" + id).onchange = safe(async () => {
    analysisPage = 1;
    await loadAnalysisJobs();
  });
$("#analysis-prev").onclick = safe(async () => {
  if (analysisPage > 1) {
    analysisPage--;
    await loadAnalysisJobs();
  }
});
$("#analysis-next").onclick = safe(async () => {
  if (analysisHasMore) {
    analysisPage++;
    await loadAnalysisJobs();
  }
});

let usageDays = [],
  selectedUsageDay = null;
function usageNumber(value) {
  return Math.max(0, Number(value) || 0);
}
function usageTick(value) {
  return new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}
function renderUsageTrend(days) {
  const focusedDay = document.activeElement?.dataset?.usageDay;
  usageDays = days;
  if (!days.some((day) => day.day === selectedUsageDay))
    selectedUsageDay = days.at(-1)?.day;
  const selected = days.find((day) => day.day === selectedUsageDay);
  const sum = (key) =>
    days.reduce((total, day) => total + usageNumber(day[key]), 0);
  const peak = Math.max(
    0,
    ...days.flatMap((day) => [
      usageNumber(day.reported),
      usageNumber(day.uncertain),
    ]),
  );
  const magnitude = 10 ** Math.floor(Math.log10(peak || 1000));
  const scale =
    ([1, 2, 2.5, 5, 10].find((step) => step * magnitude >= peak) || 10) *
    magnitude;
  const exact = (n) => usageNumber(n).toLocaleString("zh-CN");
  $("#analysis-trend").innerHTML =
    `<div class="usage-summary"><div><span>已报告／已核对</span><strong>${exact(sum("reported"))}</strong></div><div><span>未确认预留</span><strong>${exact(sum("uncertain"))}</strong></div></div><div class="usage-legend"><span><i class="reported-key"></i>已报告用量</span><span><i class="uncertain-key"></i>未确认预留 · 非实际扣费</span><small>单位：Token</small></div><div class="usage-chart" role="group" aria-label="近七天每日用量，点击日期查看详情"><div class="usage-axis" aria-hidden="true"><span>${usageTick(scale)}</span><span>${usageTick(scale / 2)}</span><span>0</span></div><div class="usage-plot"><div class="usage-grid" aria-hidden="true"><i></i><i></i><i></i></div><div class="usage-bars">${days.map((day) => `<button type="button" class="usage-day ${day.day === selectedUsageDay ? "selected" : ""}" data-usage-day="${esc(day.day)}" aria-pressed="${day.day === selectedUsageDay}" aria-label="${esc(day.day)}，已报告${exact(day.reported)}，未确认${exact(day.uncertain)}，请求${day.calls}次" title="${esc(day.day)}\n已报告 ${exact(day.reported)} Token\n未确认 ${exact(day.uncertain)} Token\n请求 ${day.calls} 次"><span class="usage-columns"><i class="reported-bar" style="height:${(usageNumber(day.reported) * 100) / scale}%"></i><i class="uncertain-bar" style="height:${(usageNumber(day.uncertain) * 100) / scale}%"></i></span><small>${esc(day.day.slice(5).replace("-", "/"))}</small></button>`).join("")}</div></div></div>${selected ? `<div class="usage-detail" aria-live="polite"><div class="usage-detail-heading"><strong>${esc(selected.day)}${selected === days.at(-1) ? " · 今天" : ""}</strong><span>请求 ${selected.calls} 次</span></div><div><span><i class="reported-key"></i>已报告／已核对</span><b>${exact(selected.reported)} Token</b></div><div><span><i class="uncertain-key"></i>未确认预留</span><b>${exact(selected.uncertain)} Token</b></div>${selected.reconciled ? "<p>本日已按确认账单校正，原始请求记录保留。</p>" : ""}</div>` : ""}<p class="hint usage-note">${sum("calls") ? "按北京时间统计。模型结果未通过校验，也可能产生已报告用量。" : "近7天暂无请求记录，图中空白日期代表零用量。"} 点击日期查看精确数值。</p>`;
  if (focusedDay) {
    [...document.querySelectorAll("[data-usage-day]")]
      .find((button) => button.dataset.usageDay === focusedDay)
      ?.focus({ preventScroll: true });
  }
}

// Archive scope and model follow-up scope are deliberately independent.
let sourcePage = 1, sourceHasMore = false, sourceRows = [];
const sourceSelection = new Set();
function renderSourceSelection() {
  $("#source-selection").textContent = `已勾选 ${sourceSelection.size} 个`;
  $("#source-add").disabled = $("#source-remove").disabled = !sourceSelection.size;
}
async function loadSources() {
  const f = new FormData($("#source-search"));
  const params = new URLSearchParams({q: f.get("q"), kind: f.get("kind"), scope: f.get("scope"), page: sourcePage});
  const d = await api("/api/crm/exemptions?" + params);
  sourceRows = d.items; sourceHasMore = d.has_more;
  $("#source-counts").textContent = `已归档 ${d.counts.total} 个会话 · 正常跟进 ${d.counts.selected} 个 · 白名单免跟进 ${d.counts.archive_only} 个`;
  $("#source-list").innerHTML = d.items.length ? d.items.map(v => `<label class="source-option"><input type="checkbox" data-followup-source="${esc(v.id)}" ${sourceSelection.has(v.id) ? "checked" : ""}><span><strong>${esc(v.title || v.source_id)}</strong><small>${v.kind === "group" ? "群聊" : "私信"} · ${esc(v.messages)} 条 · ${esc(({internal:"内部同事",buyer:"买手",provider:"纯服务商",announcement:"通知",merchant:"商家",unknown:"待识别"})[v.business_kind]||"待识别")} · ${v.followup_source ? "正常跟进" : "白名单 · 免跟进"}</small><small>${esc(v.source_id)}</small></span></label>`).join("") : empty("没有匹配会话", "先完成微信采集，或调整搜索条件。");
  $("#source-prev").disabled = sourcePage <= 1;
  $("#source-next").disabled = !sourceHasMore;
  $("#source-page").textContent = `第 ${d.page} 页 · 匹配 ${d.total} 个`;
  renderSourceSelection();
}
$("#source-list").onchange = e => {
  const id = e.target.dataset.followupSource;
  if (!id) return;
  if (e.target.checked) sourceSelection.add(id); else sourceSelection.delete(id);
  renderSourceSelection();
};
$("#source-search").onsubmit = safe(async e => { e.preventDefault(); sourcePage = 1; await loadSources(); });
$("#source-select-page").onclick = safe(async () => { sourceRows.forEach(v => sourceSelection.add(v.id)); await loadSources(); });
$("#source-clear").onclick = safe(async () => { sourceSelection.clear(); await loadSources(); });
$("#source-prev").onclick = safe(async () => { if (sourcePage > 1) { sourcePage--; await loadSources(); } });
$("#source-next").onclick = safe(async () => { if (sourceHasMore) { sourcePage++; await loadSources(); } });
async function saveSources(enabled) {
  if (!sourceSelection.size) return;
  const ids = [...sourceSelection];
  if (ids.length > 500) throw Error("单次最多更改500个会话，请分批操作。");
  const updated = await api("/api/crm/exemptions", {conversation_ids: ids, enabled});
  sourceSelection.clear();
  await load(); await loadSources();
  notice(enabled ? "已加入免跟进白名单，停止分析和今日推荐，保留历史。" : "已移出白名单，恢复已授权的客户分析。");
  const undo=document.createElement('button'); undo.textContent='撤销';
  undo.onclick=safe(async()=>{await api('/api/crm/exemptions/undo',{event_id:updated.undo_id});await load();await loadSources();notice('已恢复先前的范围与外发授权');});
  $('#notice').append(undo);

}
$("#source-add").onclick = safe(() => saveSources(true));
$("#source-remove").onclick = safe(() => saveSources(false));

$("#manage-exemptions").onclick = () => {
  go("scope");
  $("#followup-sources").scrollIntoView({behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start"});
  $("#source-search [name=scope]").value = "archive";
  $("#source-search [name=scope]").dispatchEvent(new Event("change"));
  sourcePage = 1; loadSources().catch(e => notice(e.message, true));
};
$("#clear-reviews").onclick = safe(async () => {
  $("#clear-reviews").disabled = true;
  try {
    const d = await api("/api/crm/reviews/clear", {});
    await load(); await loadReviews();
    notice(`已清空 ${d.cleared} 条待确认，客户和跟进记录保留。`);
  } finally { $("#clear-reviews").disabled = false; }
});
let monitorLoading = false;
async function loadMonitor() {
  if (monitorLoading) return;
  monitorLoading = true;
  $("#refresh-monitor").disabled = true;
  $("#monitor-note").textContent = "正在检测本机服务…";
  try {
    const d = await api("/api/monitor");
    $("#monitor-checks").innerHTML = d.checks.map(c => `<article class="monitor-item ${esc(c.state)}"><div><span class="monitor-dot"></span><strong>${esc(c.name)}</strong><span class="tag">${c.state === "ok" ? "正常" : c.state === "error" ? "异常" : "需留意"}</span></div><p>${esc(c.detail)}</p>${c.updated_at ? `<small>状态更新 ${esc(dateLabel(c.updated_at))}</small>` : ""}</article>`).join("");
    $("#monitor-note").textContent = `检测于 ${dateLabel(d.checked_at)} · ${d.note}`;
  } catch(e) { $("#monitor-note").textContent = "检测失败：" + e.message; }
  finally { monitorLoading = false; $("#refresh-monitor").disabled = false; }
}
$("#refresh-monitor").onclick = loadMonitor;
// Keep native values/forms, with one consistent accessible popover interaction.
let selectSequence = 0;
function enhanceSelects() {
  document.querySelectorAll("select:not([data-enhanced])").forEach(select => {
    select.dataset.enhanced = "true";
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    const wrapper = document.createElement("span"); wrapper.className = "select-control";
    select.before(wrapper); wrapper.append(select);
    const trigger = document.createElement("button"); trigger.type = "button"; trigger.className = "select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox"); trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-label", select.getAttribute("aria-label") || "选择选项");
    const menu = document.createElement("div"); menu.className = "select-options hidden"; menu.id = `select-menu-${++selectSequence}`; menu.setAttribute("role", "listbox"); menu.setAttribute("aria-label", trigger.getAttribute("aria-label"));
    trigger.setAttribute("aria-controls", menu.id);
    wrapper.append(trigger, menu);
    const close = () => { menu.classList.add("hidden"); trigger.setAttribute("aria-expanded", "false"); };
    const sync = () => {
      trigger.textContent = select.selectedOptions[0]?.textContent || "请选择"; trigger.disabled = select.disabled;
      menu.replaceChildren();
      [...select.options].forEach(option => {
        const button = document.createElement("button"); button.type = "button"; button.textContent = option.textContent; button.disabled = option.disabled;
        button.setAttribute("role", "option"); button.setAttribute("aria-selected", String(option.selected));
        button.onclick = () => { select.value = option.value; select.dispatchEvent(new Event("change", {bubbles: true})); close(); trigger.focus(); };
        menu.append(button);
      });
    };
    select.addEventListener("change", sync); sync();
    const open = () => {
      document.querySelectorAll('.select-trigger[aria-expanded="true"]').forEach(other => { if (other !== trigger) other.click(); });
      sync(); menu.classList.remove("hidden"); trigger.setAttribute("aria-expanded", "true");
      menu.querySelector('[aria-selected="true"]:not(:disabled)')?.focus();
    };
    trigger.onclick = () => trigger.getAttribute("aria-expanded") === "true" ? close() : open();
    wrapper.addEventListener("keydown", e => {
      if (e.key === "Escape") { close(); trigger.focus(); e.preventDefault(); }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        if (menu.classList.contains("hidden")) return open();
        const options = [...menu.querySelectorAll("button:not(:disabled)")];
        const index = options.indexOf(document.activeElement);
        const next = e.key === "Home" ? 0 : e.key === "End" ? options.length - 1 : (index + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
        options[next]?.focus();
      }
      if (e.key === "Tab") close();
    });
    wrapper.addEventListener("focusout", e => { if (!wrapper.contains(e.relatedTarget)) close(); });
  });
}
document.addEventListener("pointerdown", e => {
  document.querySelectorAll('.select-trigger[aria-expanded="true"]').forEach(trigger => { if (!trigger.parentElement.contains(e.target)) trigger.click(); });
});
enhanceSelects();
new MutationObserver(enhanceSelects).observe(document.body, {childList: true, subtree: true});

$("#source-search").addEventListener("change", safe(async e => { if (e.target.tagName === "SELECT") { sourcePage = 1; await loadSources(); } }));

function locationHTML(d) {
  if(!d) return '';
  return `<div class="location-card"><h2>回微信找到联系人</h2><p>备注：${esc(d.remark||'未提供')} · 昵称：${esc(d.nickname||'未提供')}</p><p class="hint">${d.quality==='named'?'已取得源端名称':'可从来源会话定位；微信搜索未必可用'}</p><div class="button-row">${[d.remark,d.nickname,d.alias].filter(Boolean).map(v=>`<button data-copy-location="${esc(v)}">复制 ${esc(v)}</button>`).join('')}</div>${d.conversations.map(c=>`<div class="location-row"><span>${c.kind==='group'?'群聊':'私信'} · ${esc(c.title)}</span><button data-copy-location="${esc(c.title)}">复制会话名</button><button data-conversation="${esc(c.id)}">查看原文</button></div>`).join('')}<p class="hint">复制不会发送消息或记录已联系。</p></div>`;
}
document.addEventListener('click',safe(async e=>{const b=e.target.closest('[data-copy-location],[data-person-exclude]');if(!b)return;if(b.dataset.copyLocation){await navigator.clipboard.writeText(b.dataset.copyLocation);notice('已复制，请在微信搜索或进入来源群定位');}else{await api('/api/crm/people/'+encodeURIComponent(b.dataset.personExclude)+'/exclusion',{enabled:b.dataset.enabled==='true'});await loadPeople();await load();notice('人物跟进范围已更新，其他群成员不受影响');}}));
let peopleRequest=0;
async function loadPeople(){const ticket=++peopleRequest;const d=await api('/api/crm/people?q='+encodeURIComponent($('#people-search').value));if(ticket!==peopleRequest)return;$('#people-list').innerHTML=d.map(v=>`<div class="location-row"><span><strong>${esc(v.name)}</strong><small>${esc(v.source_id)} · ${v.excluded?'已免跟进':'正常'}</small></span><button data-person-exclude="${esc(v.id)}" data-enabled="${!v.excluded}">${v.excluded?'恢复':'免跟进此人'}</button></div>`).join('')||empty('未找到联系人','先同步微信联系人或等待消息采集。');}
$('#people-search').oninput=()=>{clearTimeout(loadPeople.timer);loadPeople.timer=setTimeout(()=>loadPeople().catch(e=>notice(e.message,true)),200);};
$('#sync-identity').onclick=safe(async()=>{const b=$('#sync-identity');b.disabled=true;try{const d=await api('/api/identity/sync',{});const audit=await api('/api/identity/audit');$('#identity-audit').textContent=`已同步 ${d.contacts} 位联系人 · ${audit.unresolved_names} 位名称待补全`;await load();notice('联系人已更新，不需要重新导入聊天或调用模型');}finally{b.disabled=false;}});
