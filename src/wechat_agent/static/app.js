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
    "微信客户助手 · " +
    {
      today: "今日跟进",
      customers: "客户",
      reviews: "待确认",
      settings: "设置",
    }[page];
  if (page === "customers")
    loadCustomers().catch((e) => notice(e.message, true));
  if (page === "reviews") loadReviews().catch((e) => notice(e.message, true));
  if (page === "settings") renderSettings();
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
  const complete = jobs.succeeded || 0,
    total = (state.jobs || []).reduce((n, j) => n + j.n, 0);
  $("#progress").classList.toggle("hidden", !total);
  $("#progress").textContent =
    `聊天 ${state.messages || 0} 条 · 分析分片 ${complete} / ${total} 完成` +
    (jobs.blocked_budget ? " · 已到今日预算，可调整预算或次日续跑" : "") +
    (jobs.failed ? " · 部分分析失败，可在设置重试" : "") +
    (jobs.blocked_credentials ? " · API 凭据需检查" : "") +
    " · 媒体尚未自动识别";
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
            `<article class="action-card"><div class="avatar">${esc(a.customer_name.slice(0, 1))}</div><div><div class="card-heading"><h3>${esc(a.customer_name)}</h3><span class="tag ${a.due_date < state.today && a.state === "open" ? "amber" : ""}">${esc(statusNames[a.state] || a.state)}</span></div><div class="card-meta">${esc(a.opportunity || "客户跟进")} · ${esc(a.due_date || "时间待定")}${a.date_kind === "suggested" ? "（建议）" : ""} · 联系 ${esc(a.contact_name || a.customer_name)}</div><h2>${esc(a.summary)}</h2><div class="reason">为什么：${esc(a.reason)}${!a.evidence_valid ? " · 原始依据已变化，等待重算" : ""}</div><div class="card-actions"><button data-evidence="${esc(a.id)}">查看依据</button><button data-draft="${esc(a.id)}" ${a.do_not_contact || !a.evidence_valid || ["done", "cancelled", "historical_unresolved"].includes(a.state) ? "disabled" : ""}>查看话术</button><button data-result="${esc(a.id)}">记录结果</button><button data-postpone="${esc(a.id)}">改期</button><button class="quiet" data-customer="${esc(a.customer_id)}">客户档案 ↗</button></div></div></article>`,
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
    ? "已绑定工作账号：" + state.account_id
    : "尚未确认工作账号";
  $("#key-status").textContent = state.key_configured
    ? "已检测到本机 API key；实际可用性以请求结果为准。"
    : "尚未配置 API key。";
  $("#key-form").classList.toggle("hidden", !!state.key_configured);
  $("#change-key").classList.toggle("hidden", !state.key_configured);
  $("#policy-form [name=daily_budget]").value =
    state.policy?.daily_budget || 100000;
  $("#policy-form [name=include_new]").checked =
    state.policy?.include_new !== 0;
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
    `<div class="button-row"><button data-dnc="${esc(id)}" data-current="${d.customer.do_not_contact}">${d.customer.do_not_contact ? "恢复联系建议" : "暂停联系此客户"}</button></div><h2>客户近况</h2>${facts.length ? facts.map((f) => `<div class="fact"><strong>${esc(fields[f.field] || f.field)} · ${f.locked ? "人工确认" : "对话提取"}</strong><p>${esc(f.value)}</p><details><summary class="hint">查看来源／纠正</summary><button data-correct-fact="${esc(f.id)}" data-value="${esc(f.value)}" data-owner="${esc(id)}">纠正此项</button>${messageHTML(f.sources.map((m) => ({ ...m, evidence_label: true })))}</details></div>`).join("") : '<p class="hint">尚无已验证的详细需求，未知字段不会要求你逐一补填。</p>'}<h2>当前机会与计划</h2>${d.plans.map((p) => `<p>${esc(p.name)} <span class="tag">${esc(p.stage)}</span></p>`).join("") || '<p class="hint">尚未识别具体业务机会。</p>'}<h2>沟通重点</h2><p class="hint">最近 300 条可见私信与此联系人的群发言；完整会话在设置中的消息档案查看。</p>${messageSection(d.messages)}`,
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
  if (currentPage === "settings") renderSettings();
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
    `<div class="inset">检测到 ${esc(d.display_name || d.account_id)}<p class="hint">${esc(d.account_id)}</p><button id="bind-account" data-account="${esc(d.account_id)}">确认这是我的工作账号</button></div>`;
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
    include_new: f.has("include_new"),
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
