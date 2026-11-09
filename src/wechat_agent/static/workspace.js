import "./workspace/select.js";
import {
  $,
  esc,
  api,
  copy,
  time,
  errorText,
  notice,
} from "./workspace/client.js";
import { renderSettings } from "./workspace/settings.js";
import { renderScope } from "./workspace/scope.js";
import { customerHTML, evidence, mediaControls } from "./workspace/customer.js";
import { closeImage } from "./workspace/media.js";
let view = [
    "today",
    "customers",
    "review",
    "pilot",
    "settings",
    "scope",
  ].includes(
    new URLSearchParams(location.search).get("view") ||
      new URLSearchParams(location.search).get("page"),
  )
    ? new URLSearchParams(location.search).get("view") ||
      new URLSearchParams(location.search).get("page")
    : "today",
  taskView = "today",
  progressPage = 1,
  progressRequest = 0,
  documents = [],
  selected,
  focusBefore,
  busy = false,
  candidatePage = 1,
  candidateQuery = "",
  candidateSource = "",
  candidateRequest = 0,
  candidateItems = [],
  candidateTimer,
  timelineQuery = "",
  customerQuery = "",
  customerStage = "all",
  customerPage = 1;
const stages = {
  needs: "需求确认",
  quoting: "报价沟通",
  decision: "商家决策",
  preparing: "备货中",
  fulfillment: "已走货 · 后续对接",
  reported_shipped: "已报告发货",
  closed: "已结束",
};
async function refresh() {
  const current = view;
  const data = await api("documents");
  documents = data.items;
  if (current === view)
    $("#status").textContent = data.stale_documents
      ? `${data.stale_documents} 份档案依据已变化，已暂时退出展示，请重新分析。`
      : "";
  if (current === view) render();
}
function active(d) {
  const ids =
    taskView === "today" ? d.today_action_ids : d.task_groups?.[taskView];
  return (ids || []).map((id) => [id, d.body.actions[id]]);
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
    pilot: "整理与进度",
    settings: "设置与接入",
    scope: "会话范围",
  }[view];
  if (view === "settings" || view === "scope") {
    (view === "settings" ? renderSettings() : renderScope()).catch(
      (e) => ($("#status").textContent = e.message),
    );
    return;
  }
  if (view === "pilot") {
    pilot();
    return;
  }
  let list = documents.filter((d) =>
    view === "today"
      ? active(d).length
      : view === "review"
        ? Object.values(d.body.decisions).some((q) => !q.resolved) ||
          Object.values(d.body.actions).some((a) => a.state === "proposed") ||
          !!d.body.unattributed?.length
        : d.body.relationship === "merchant",
  );
  if (view === "customers")
    list = list.filter(
      (d) =>
        [
          d.name,
          d.source_id,
          ...d.location.conversations.map((c) => c.title),
        ].some((t) =>
          t.toLocaleLowerCase().includes(customerQuery.toLocaleLowerCase()),
        ) &&
        (customerStage === "all" ||
          Object.values(d.body.batches).some((b) => b.stage === customerStage)),
    );
  const total = list.length;
  customerPage = Math.min(customerPage, Math.max(1, Math.ceil(total / 50)));
  if (view === "customers")
    list = list.slice((customerPage - 1) * 50, customerPage * 50);
  $("#content").innerHTML =
    (view === "customers"
      ? `<form id="customer-search" class="search-form customer-filters"><label class="candidate-search">搜索客户<input name="q" maxlength="200" placeholder="姓名、备注或来源群名" value="${esc(customerQuery)}"></label><label>备货阶段<select name="stage"><option value="all">全部阶段</option>${Object.entries(
          stages,
        )
          .map(
            ([k, n]) =>
              `<option value="${k}" ${customerStage === k ? "selected" : ""}>${n}</option>`,
          )
          .join(
            "",
          )}</select></label><button>查找客户</button></form><p class="meta">${total}位商家 · 每页最多50位 · 白名单内人物不展示</p>`
      : "") +
    (view === "today"
      ? `<div class="toolbar segments" role="tablist" aria-label="待办状态">${Object.entries(
          {
            today: "今日到期",
            upcoming: "后续安排",
            waiting: "等待回复",
            done: "已完成",
          },
        )
          .map(
            ([key, label]) =>
              `<button role="tab" data-task-view="${key}" aria-selected="${taskView === key}">${label}</button>`,
          )
          .join("")}</div>`
      : "") +
    '<div class="cards">' +
    (list
      .map(
        (d) =>
          `<article class="card"><div class="row"><div><h2>${esc(d.name)}</h2><span class="meta">版本 ${d.version} · ${d.body.coverage.complete_context ? "相关资料分册已完成" : "资料覆盖有限，行动建议需确认"}${d.body.paused ? " · 已暂停联系" : ""}${d.needs_update ? " · 新进展待整理" : ""}</span></div><button data-open="${esc(d.id)}" class="primary">查看档案</button></div><p class="reason">${esc(
            view === "today"
              ? active(d)[0][1].text
              : Object.values(d.body.notes)[0]?.text ||
                  Object.values(d.body.batches)
                    .map((b) => stages[b.stage])
                    .join(" · ") ||
                  "尚未形成可靠摘要",
          )}</p></article>`,
      )
      .join("") ||
      '<div class="empty"><h2>当前没有可展示的结果</h2><p class="muted">可在“整理与进度”开启自动整理，或选择一位联系人分析。无必要行动、身份未明确或覆盖不足时，不会强行创建待办。</p></div>') +
    "</div>" +
    (view === "customers"
      ? `<div class="toolbar spaced"><button id="customers-prev" ${customerPage > 1 ? "" : "disabled"}>上一页客户</button><span>第${customerPage}页</span><button id="customers-next" ${customerPage * 50 < total ? "" : "disabled"}>下一页客户</button></div>`
      : "");
}
const candidateBlocks = {
  analysis_disabled:
    "尚未开启文本分析授权。前往设置确认范围和分析授权后，返回刷新联系人。",
  key_missing: "尚未配置 DeepSeek key。前往设置保存后，返回刷新联系人。",
  source_unauthorized:
    "此联系人的来源会话尚未授权外发。前往会话范围检查分析授权。",
  no_text:
    "此联系人暂无已授权的完整文本，现有图片或不完整记录不能用于本次分析。",
};
const emptyCandidates = {
  account_unbound: [
    "尚未绑定工作微信",
    "请在设置与接入中检测连接并确认工作账号。",
    "settings",
  ],
  no_archive: [
    "当前账号尚无归档消息",
    "请在设置与接入中检查 wx-cli 与采集状态；已有归档时，请核对绑定账号和启动时的数据目录，无需重复导入。",
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
  const option = candidateItems.find((c) => c.source_id === candidateSource);
  const reason = option?.blocked_reason;
  if (!option) candidateSource = "";
  if (!$("#analyze")) return;
  $("#analyze").disabled = busy || !option || !!reason;
  $("#candidate-readiness").textContent = reason
    ? candidateBlocks[reason]
    : option
      ? `已选：${option.name}。仅分析授权范围内的文本。`
      : "输入姓名搜索，再点击一个匹配联系人。";
}

async function scanProgress() {
  const ticket = ++progressRequest;
  const data = await api("progress?page=" + progressPage);
  const target = $("#scan-progress");
  if (!target || view !== "pilot" || ticket !== progressRequest) return;
  progressPage = data.page;
  const phases = {
    collect: "整理原始资料",
    merge: "合并资料分册",
    summarize: "总结客户档案",
    done: "等待更新",
    queued: "等待开始",
  };
  const states = {
    queued: "等待整理",
    running: "正在整理",
    paused: "已暂停",
    failed: "需要处理",
  };
  target.innerHTML = `<p class="meta">按客户归纳 · 最新更新在前 · 已完成自动移出 · 每页20位</p><div class="cards">${data.items.map((s) => `<article class="insight-card progress-card" data-progress-source="${esc(s.source_id)}"><div class="row"><div><h3>${esc(s.name)}</h3><p class="meta">${esc(states[s.status] || s.status)} · ${esc(phases[s.phase] || s.phase)}</p></div><button data-progress-action="${["running", "queued"].includes(s.status) ? "pause" : "resume"}" data-source="${esc(s.source_id)}">${["running", "queued"].includes(s.status) ? "暂停分析" : s.status === "failed" ? "重试分析" : "继续分析"}</button></div>${s.total_pages ? `<p>分册 ${s.completed_pages} / ${s.total_pages} · 已整理 ${s.processed_messages} / ${s.source_messages} 条</p>` : "<p class='meta'>开始后将完整整理该客户的相关聊天。</p>"}${s.error ? `<p class="${s.status === "failed" ? "error" : "meta"}">${esc(errorText(s.error))}</p>` : ""}<p class="meta">更新于 ${esc(time(s.updated_at))} 北京时间</p></article>`).join("") || '<p class="progress-empty">当前没有进行中的整理任务。已完成的档案可在“客户”中查看。</p>'}</div><div class="toolbar progress-pagination"><button id="progress-prev" ${data.page === 1 ? "disabled" : ""}>上一页</button><span class="meta">第 ${data.page} / ${data.pages} 页 · ${data.total} 位客户</span><button id="progress-next" ${data.has_more ? "" : "disabled"}>下一页</button></div>`;
}
setInterval(() => {
  if (
    view === "pilot" &&
    !$("#auto-queue :focus") &&
    !$("#scan-progress :focus")
  ) {
    scanProgress().catch(() => {});
    queueProgress().catch(() => {});
  }
}, 5000);
async function pilot() {
  const ticket = ++candidateRequest;
  try {
    const params = new URLSearchParams({
      page: candidatePage,
      q: candidateQuery,
    });
    const data = await api("candidates?" + params);
    if (view !== "pilot" || ticket !== candidateRequest) return;
    candidatePage = data.page;
    candidateItems = data.items;
    const d = data.diagnostics;
    const empty = emptyCandidates[d.empty_reason];
    const search = `<form id="candidate-search" class="toolbar spaced"><label class="candidate-search">搜索联系人<input name="q" maxlength="100" value="${esc(candidateQuery)}" placeholder="备注、昵称或微信 ID"></label></form>`;
    const picker = data.items.length
      ? `<div class="candidate-results" aria-label="匹配联系人">${data.items.map((c) => `<button type="button" data-candidate="${esc(c.source_id)}" aria-pressed="${c.source_id === candidateSource}"><strong>${esc(c.name)}</strong><small>${esc(c.source_id)}</small></button>`).join("")}</div><div class="toolbar spaced"><button id="prev" ${candidatePage === 1 ? "disabled" : ""}>上一页</button><span>第 ${candidatePage} 页 · ${data.total} 位来源联系人 · 每页最多 50 位</span><button id="next" ${!data.has_more ? "disabled" : ""}>下一页</button></div><p id="candidate-readiness" class="muted" role="status"></p><button class="primary spaced" id="analyze" disabled>${busy ? "正在分析，请稍候…" : "分析此联系人"}</button>`
      : `<div class="candidate-empty spaced" role="status"><h3>${empty ? empty[0] : "没有匹配的联系人"}</h3><p>${empty ? empty[1] : "请尝试其他备注、昵称或微信 ID，或清空搜索后重试。"}</p>${empty ? `<a href="/workspace?view=${empty[2]}">${empty[2] === "settings" ? "前往连接与模型设置" : "检查会话范围与人物白名单"} →</a>` : '<button id="clear-candidate-search">清空搜索</button>'}</div>`;
    $("#content").innerHTML =
      `<div id="auto-queue"></div><div class="card spaced"><div class="toolbar"><h2>手动分析一位联系人</h2><button id="refresh-candidates">刷新联系人</button></div><p class="muted">联系人从本机归档读取，查看列表不调用模型。点击分析才会调用 DeepSeek，仅记录用量；先完整整理来源分册，再总结；进度可暂停、续跑。</p><p class="meta">当前账号已归档 ${d.archived_messages} 条消息 · 正常跟进 ${d.scope_conversations} 个会话 · 可识别 ${d.contacts} 位联系人</p>${search}${picker}<div class="toolbar spaced"><a href="/workspace?view=settings">模型与分析授权设置 →</a><a href="/workspace?view=scope">会话范围与白名单 →</a></div><p class="meta">修改设置后返回刷新。不会启动全库重建。图片保留占位；长历史分册整理，暂停后可继续。</p></div>`;
    $("#auto-queue").insertAdjacentHTML(
      "afterend",
      '<section class="card spaced"><h2>客户资料整理进度</h2><div id="scan-progress" role="status">正在读取进度…</div></section>',
    );
    if (data.items.length) updateCandidateButton();
    await scanProgress();
    await queueProgress();
  } catch (e) {
    if (view === "pilot" && ticket === candidateRequest)
      $("#status").textContent = e.message;
  }
}
document.addEventListener("input", (e) => {
  if (e.target.name !== "q" || !e.target.closest("#candidate-search")) return;
  candidateQuery = e.target.value;
  candidateSource = "";
  candidatePage = 1;
  ++candidateRequest;
  updateCandidateButton();
  clearTimeout(candidateTimer);
  candidateTimer = setTimeout(async () => {
    await pilot();
    if (view === "pilot") {
      const input = $("#candidate-search input");
      input?.focus();
      input?.setSelectionRange(input.value.length, input.value.length);
    }
  }, 250);
});
document.addEventListener(
  "toggle",
  (e) => {
    if (e.target.id === "packet-disclosure") {
      $("#packet-label").textContent = e.target.open
        ? "收起已保存资料分册"
        : "查看已保存资料分册";
      if (e.target.open && !e.target.dataset.loaded)
        loadPackets(1).catch(
          (error) =>
            ($("#detail-status").textContent = errorText(error.message)),
        );
    }
  },
  true,
);
document.addEventListener("change", (e) => {
  if (
    e.target.name === "action_id" &&
    e.target.closest("#customer-followup-form")
  ) {
    const f = e.target.form;
    f.elements.action_state.disabled = !e.target.value;
    f.elements.next_date.disabled = !e.target.value;
    if (!e.target.value) {
      f.elements.action_state.value = "keep";
      f.elements.next_date.value = "";
    }
  }
  if (e.target.id === "contact") updateCandidateButton();
});
document.addEventListener("submit", async (e) => {
  if (e.target.dataset.clueReview) {
    e.preventDefault();
    const form = e.target,
      b = form.querySelector("button");
    b.disabled = true;
    try {
      const f = new FormData(form);
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: "resolve_clue",
        target: form.dataset.clueReview,
        value: {
          choice: "confirmed",
          text: f.get("text"),
          belongs_to_customer: f.has("belongs"),
        },
      });
      await api("queue/refresh", {});
      await reloadClues("已核实并保存到客户资料；未创建待办。");
    } catch (error) {
      $("#detail-status").textContent = errorText(error.message);
      if (b.isConnected) b.disabled = false;
    }
    return;
  }
  if (e.target.id === "customer-search") {
    e.preventDefault();
    const f = new FormData(e.target);
    customerQuery = f.get("q").trim();
    customerStage = f.get("stage");
    customerPage = 1;
    render();
    return;
  }
  if (e.target.id === "customer-timeline-search") {
    e.preventDefault();
    timelineQuery = new FormData(e.target).get("q").trim();
    document.querySelector('[data-ledger="1"]').click();
    return;
  }
  if (e.target.id === "customer-followup-form") {
    e.preventDefault();
    const form = e.target;
    const b = form.querySelector("button[type=submit]");
    b.disabled = true;
    try {
      const f = new FormData(form),
        value = {
          outcome: f.get("outcome"),
          note: f.get("note"),
          action_id: f.get("action_id") || null,
          action_state: f.get("action_state") || "keep",
          next_date: f.get("next_date") || null,
        };
      const id = selected.id;
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: "followup",
        value,
      });
      await api("queue/refresh", {});
      close();
      await refresh();
      await openDetail(id);
      detailTab("journal");
      await loadJournal();
      $("#detail-status").textContent = "人工跟进已保存。";
    } catch (error) {
      $("#detail-status").textContent = error.message;
      if (b.isConnected) b.disabled = false;
    }
    return;
  }
  if (e.target.id !== "candidate-search") return;
  e.preventDefault();
  candidateQuery = new FormData(e.target).get("q").trim();
  candidatePage = 1;
  pilot();
});

async function queueProgress() {
  const q = await api("queue");
  const target = $("#auto-queue");
  if (!target || view !== "pilot") return;
  const gates = {
    paused: "自动整理已暂停；可单独继续一位客户",
    manual_mode: "当前仅支持手动分析；使用 wechat-agent start 启动自动整理",
    awaiting_account: "请先绑定工作微信",
    legacy_mode: "请使用 wechat-agent start 启动客户整理",
    blocked_policy: "请先在设置开启文本分析授权",
    blocked_credentials: "请先配置 DeepSeek key",
  };
  target.innerHTML = `<section class="card"><h2>按客户自动整理</h2><p class="muted">先完整整理每位客户的历史，再总结档案。优先近15天活跃客户，已完成分册可复用。</p><div class="toolbar"><button class="${q.enabled ? "" : "primary"}" id="automation-toggle" data-enabled="${!q.enabled}">${q.enabled ? "暂停自动整理" : "开启自动整理"}</button><button id="queue-refresh">刷新会话与队列</button>${q.enabled && q.gate && !["manual_mode", "legacy_mode", "blocked_policy", "blocked_credentials"].includes(q.gate) ? '<button id="queue-resume">问题已处理，恢复队列</button>' : ""}</div><p role="status">${esc(q.gate ? gates[q.gate] || errorText(q.gate) : "队列运行中；新消息将更新对应客户")}${!q.background ? " · 当前服务未启用后台，请使用 wechat-agent start" : ""}</p><p class="meta">待整理 ${q.counts.queued || 0} · 整理中 ${q.counts.running || 0} · 暂停或等待续跑 ${q.counts.paused || 0} · 需要处理 ${q.counts.failed || 0}</p><p class="meta">单客户暂停不影响其他客户；继续时复用已整理分册。仅记录用量，不设每日 Token 上限。</p></section>`;
}

async function loadPackets(page) {
  const target = $("#packet-ledger"),
    disclosure = $("#packet-disclosure"),
    source = selected.source_id;
  disclosure.dataset.loaded = "loading";
  target.setAttribute("aria-busy", "true");
  if (!target.childNodes.length) target.textContent = "正在读取已保存资料…";
  try {
    const data = await api(
      "packets?" + new URLSearchParams({ source_id: source, page }),
    );
    if (!target.isConnected || selected.source_id !== source) return;
    target.innerHTML = `<p class="meta">资料分册历史 · 第${page}页；我方是你的工作微信。其他参与人或归属不明的内容不等于客户事实。</p>${data.items.map((p) => `<section class="insight-card"><h4>${p.kind === "extract" ? "原始资料整理" : "分册汇总"}</h4>${p.body.facts.map((f) => `<article class="evidence"><p class="meta">${esc(f.subject_label || { customer: "关联客户", other: "其他参与人", unclear: "归属待核实" }[f.subject])}</p><p>${esc(f.text)}</p>${evidence(f.evidence, p)}</article>`).join("")}</section>`).join("") || "<p>暂无可展示的有效分册。</p>"}<div class="button-group">${page > 1 ? `<button data-packets="${page - 1}">上一页分册</button>` : ""}${data.has_more ? `<button data-packets="${page + 1}">下一页分册</button>` : ""}</div>`;
    disclosure.dataset.loaded = "ready";
  } catch (error) {
    if (target.isConnected) {
      delete disclosure.dataset.loaded;
      target.innerHTML = `<p>${esc(errorText(error.message))}</p><button data-packets="${page}">重新加载资料分册</button>`;
    }
  } finally {
    target.removeAttribute("aria-busy");
  }
}
async function reloadClues(message) {
  const source = selected.source_id,
    scroll = $("dialog").scrollTop;
  const drafts = [...document.querySelectorAll("[data-clue-review]")].map(
    (form) => ({
      id: form.dataset.clueReview,
      text: form.elements.text.value,
      belongs: form.elements.belongs.checked,
      open: form.parentElement.open,
    }),
  );
  await refresh();
  selected = await api(
    "customer?" + new URLSearchParams({ source_id: source }),
  );
  closeImage();
  $("#detail").innerHTML = customerHTML(selected);
  detailTab("overview");
  for (const draft of drafts) {
    const form = document.querySelector(
      '[data-clue-review="' + draft.id + '"]',
    );
    if (form) {
      form.elements.text.value = draft.text;
      form.elements.belongs.checked = draft.belongs;
      form.parentElement.open = draft.open;
    }
  }
  for (const id of ["#clue-disclosure", "#reviewed-clues"])
    if ($(id)) $(id).open = true;
  $("dialog").scrollTop = scroll;
  $("#detail-status").textContent = message;
  const summary =
    $("#reviewed-clues > summary") || $("#clue-disclosure > summary");
  summary?.focus({ preventScroll: true });
}
async function openDetail(id) {
  const summary = documents.find((d) => d.id === id);
  selected = await api(
    "customer?" + new URLSearchParams({ source_id: summary.source_id }),
  );
  const d = selected;
  focusBefore = document.activeElement;
  $("#detail-title").textContent = d.name;
  $("#detail-status").textContent = "";
  timelineQuery = "";
  closeImage();
  $("#detail").innerHTML = customerHTML(d);
  $("dialog").showModal();
  $("dialog").scrollTop = 0;
  const initial = view === "today" || view === "review" ? "work" : "overview";
  detailTab(initial);
}
function detailTab(key) {
  document
    .querySelectorAll("[data-detail-panel]")
    .forEach((panel) => (panel.hidden = panel.dataset.detailPanel !== key));
  document.querySelectorAll("[data-detail-tab]").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.detailTab === key));
    b.tabIndex = b.dataset.detailTab === key ? 0 : -1;
  });
}
async function loadJournal(page = 1) {
  const data = await api(
    "journal?" + new URLSearchParams({ source_id: selected.source_id, page }),
  );
  $("#customer-journal").innerHTML =
    data.items
      .map(
        (r) =>
          `<article class="insight-card"><p class="meta">${esc(time(r.created_at))} 北京时间 · 人工记录 · ${esc({ contacted: "已联系", replied: "已收到反馈", no_reply: "暂未回复", note: "备注" }[r.outcome])}</p><p>${esc(r.note)}</p>${r.next_date ? `<p>下次联系：${esc(r.next_date)}</p>` : ""}</article>`,
      )
      .join("") || "<p>暂无人工跟进记录。</p>";
  $("#customer-journal").innerHTML +=
    `${page > 1 ? `<button data-journal="${page - 1}">上一页记录</button>` : ""}${data.has_more ? `<button data-journal="${page + 1}">下一页记录</button>` : ""}`;
}

function close() {
  $("dialog").close();
  closeImage();
  if (focusBefore?.isConnected) focusBefore.focus();
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
    if (b.id === "customers-prev" || b.id === "customers-next") {
      customerPage += b.id === "customers-next" ? 1 : -1;
      render();
    }
    if (b.dataset.detailTab) detailTab(b.dataset.detailTab);
    if (b.dataset.dismissClue || b.dataset.restoreClue) {
      b.disabled = true;
      const restore = !!b.dataset.restoreClue;
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: restore ? "restore_clue" : "resolve_clue",
        target: b.dataset.restoreClue || b.dataset.dismissClue,
        ...(restore ? {} : { value: { choice: "dismissed" } }),
      });
      await api("queue/refresh", {});
      await reloadClues(
        restore
          ? "已撤销判断，恢复为待核实线索。"
          : "已不采纳，可在已处理线索中撤销。",
      );
      return;
    }
    if (b.id === "copy-contact-name")
      await copy(
        selected.location.remark ||
          selected.location.nickname ||
          selected.source_id,
      );
    if (b.id === "exempt-customer") {
      b.disabled = true;
      await api(
        "/api/crm/people/" +
          encodeURIComponent(selected.actor_id) +
          "/exclusion",
        { enabled: true },
      );
      await api("queue/refresh", {});
      close();
      await refresh();
      $("#status").textContent = "已加入免跟进白名单，完整原始记录保留。";
    }
    if (b.id === "load-customer-history") {
      const rows = await api(
        "history?" + new URLSearchParams({ source_id: selected.source_id }),
      );
      $("#customer-history").innerHTML = rows
        .map(
          (r) =>
            `<p class="meta">版本 ${r.version} · ${esc(r.reason === "agent" ? "自动整理" : "人工修改")} · ${esc(time(r.created_at))} 北京时间</p>`,
        )
        .join("");
    }
    if (b.dataset.saveStage) {
      const id = b.dataset.saveStage;
      b.disabled = true;
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: "batch_stage",
        target: id,
        value: {
          stage: $("#stage-" + id).value,
          note: $("#stage-note-" + id).value,
        },
      });
      close();
      await refresh();
      $("#status").textContent = "批次判断已保存，后台将按人工约束继续整理。";
    }
    if (b.dataset.draft) {
      const id = b.dataset.draft;
      b.disabled = true;
      b.textContent = "正在准备草稿…";
      const draft = await api("draft", {
        source_id: selected.source_id,
        version: selected.version,
        action_id: id,
      });
      $("#draft-" + id).innerHTML =
        `<label>人工核对并编辑<textarea id="draft-text-${id}" rows="4" maxlength="1200">${esc(draft.text)}</textarea></label>${evidence(draft.evidence, selected)}<button data-copy-draft="${id}">复制草稿</button><p class="meta">尚未发送，也不会自动标记已联系。确认发送后可到人工跟进中记录。</p>`;
      b.textContent = "重新查看草稿";
      b.disabled = false;
    }
    if (b.dataset.copyDraft)
      await copy($("#draft-text-" + b.dataset.copyDraft).value);
    if (b.dataset.journal) await loadJournal(Number(b.dataset.journal));
    if (b.dataset.taskView) {
      taskView = b.dataset.taskView;
      render();
    }
    if (b.id === "automation-toggle" || b.id === "queue-resume") {
      b.disabled = true;
      await api("automation", {
        enabled: b.id === "queue-resume" || b.dataset.enabled === "true",
      });
      await queueProgress();
      await scanProgress();
    }
    if (b.id === "queue-refresh") {
      b.disabled = true;
      await api("queue/refresh", {});
      await queueProgress();
      await scanProgress();
    }
    if (b.id === "progress-prev" || b.id === "progress-next") {
      progressPage += b.id === "progress-next" ? 1 : -1;
      await scanProgress();
    }
    if (b.dataset.progressAction) {
      b.disabled = true;
      const source = b.dataset.source;
      const action = b.dataset.progressAction;
      const result = await api("progress/control", {
        source_id: source,
        action,
      });
      await scanProgress();
      await queueProgress();
      if (action === "resume" && !result.automatic) {
        notice("正在继续分析，已整理分册会复用。");
        const analyzed = await api("analyze", { source_id: source });
        await refresh();
        notice(
          analyzed.paused
            ? "进度已保存，可继续分析。"
            : "分析完成，档案已更新。",
        );
        await scanProgress();
      } else {
        notice(
          action === "pause"
            ? "已暂停该客户；当前请求结束后停止，已整理分册保留。"
            : "已安排继续分析，复用已整理分册。",
        );
      }
    }
    if (b.dataset.candidate) {
      candidateSource = b.dataset.candidate;
      document
        .querySelectorAll("[data-candidate]")
        .forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      updateCandidateButton();
      scanProgress().catch(() => {});
    }
    if (b.dataset.view) {
      view = b.dataset.view;
      history.pushState({}, "", "/workspace?view=" + view);
      if (["today", "customers", "review"].includes(view)) await refresh();
      else render();
    }
    if (b.dataset.open) {
      b.disabled = true;
      await openDetail(b.dataset.open);
      b.disabled = false;
    }
    if (b.dataset.packets) {
      b.disabled = true;
      await loadPackets(Number(b.dataset.packets));
      if (b.isConnected) b.disabled = false;
    }
    if (b.dataset.ledger) {
      b.disabled = true;
      const page = Number(b.dataset.ledger);
      const data = await api(
        "sources?" +
          new URLSearchParams({
            source_id: selected.source_id,
            page,
            order: "oldest",
            q: timelineQuery,
          }),
      );
      $("#source-ledger").innerHTML =
        `<p class="meta">全部相关会话共 ${data.total} 条 · 第 ${data.page} 页 · 每页 50 条</p>${data.items.map((m) => `<article class="insight-card"><p class="meta">${esc(m.conversation)} · ${esc(m.direction === "outgoing" ? "我方" : m.sender_name || m.sender_id)} · ${esc(new Date(m.event_time).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }))}</p><p>${esc(m.text)}</p>${mediaControls(m)}</article>`).join("")}${page > 1 ? `<button data-ledger="${page - 1}">上一页来源</button>` : ""}${data.has_more ? `<button data-ledger="${page + 1}">下一页来源</button>` : ""}`;
      b.disabled = false;
    }
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
      const source = candidateSource;
      busy = true;
      b.disabled = true;
      b.textContent = "正在分析，请稍候…";
      $("#status").textContent = "正在检索并整理该联系人…";
      try {
        const result = await api("analyze", { source_id: source });
        await refresh();
        $("#status").textContent = result.paused
          ? "资料整理已保存并暂停。可在整理进度中继续分析。"
          : "分析完成。可在客户或待确认中查看；无业务依据时不会创建客户。";
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
    if (e.message === "workspace_version_conflict") await refresh();
    const messages = {
      workspace_version_conflict:
        "档案已被后台更新，本次修改尚未保存。请关闭详情，重新核对后保存。",
      workspace_closed_batch: "该批次已走货或结束，不能恢复备货待办。",
      workspace_role_required: "请先确认该联系人是商家。",
      workspace_already_running:
        "此联系人正在后台整理，可在进度区查看，无需重复启动。",
      workspace_invalid_date: "请选择今天或之后的有效日期。",
    };
    ($("dialog").open ? $("#detail-status") : $("#status")).textContent =
      messages[e.message] || errorText(e.message);
    b.disabled = false;
  }
});
$("dialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  close();
});
refresh().catch((e) => ($("#status").textContent = e.message));

setInterval(() => {
  if (
    ["today", "customers", "review"].includes(view) &&
    !$("dialog").open &&
    !busy
  )
    refresh().catch(() => {});
}, 30000);

addEventListener("popstate", () => {
  const next = new URLSearchParams(location.search).get("view") || "today";
  view = [
    "today",
    "customers",
    "review",
    "pilot",
    "settings",
    "scope",
  ].includes(next)
    ? next
    : "today";
  if ($("dialog").open) close();
  refresh().catch((e) => ($("#status").textContent = e.message));
});

document.addEventListener("keydown", (e) => {
  const tab = e.target.closest("[data-detail-tab]");
  if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
    return;
  e.preventDefault();
  const tabs = [...document.querySelectorAll("[data-detail-tab]")],
    index = tabs.indexOf(tab);
  const next =
    e.key === "Home"
      ? 0
      : e.key === "End"
        ? tabs.length - 1
        : (index + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
          tabs.length;
  detailTab(tabs[next].dataset.detailTab);
  tabs[next].focus();
});
