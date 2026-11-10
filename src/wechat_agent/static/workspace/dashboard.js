import { $, esc, api, notice, errorText } from "./client.js";
import { taskStages } from "./progress.js";
let query = "",
  selected = "all",
  page = 1,
  followup = "all",
  followupPage = 1,
  ticket = 0,
  polling = false;
const active = () => !!$("[data-view=dashboard][aria-current=page]");
const pending = new Set();
const roles = {
  merchant: "商家",
  candidate: "待识别身份",
  non_target: "非商家",
  unclassified: "尚未整理",
};
export function selectDashboard(filter) {
  selected = filter;
  page = 1;
}
const columns =
  '<div class="board-columns" aria-hidden="true"><span>联系人</span><span>档案摘要</span><span>待办与确认</span><span>整理进度</span><span>操作</span></div>';
export async function renderDashboard() {
  if (!active()) return;
  if (!$("#dashboard-view"))
    $("#content").innerHTML =
      `<div id="dashboard-view"><div id="dashboard-metrics" class="dashboard-metrics"></div><section class="card board-controls"><div class="board-heading"><h2>客户与整理</h2><div id="dashboard-automation" class="toolbar"></div></div><form id="dashboard-search" class="search-form"><label class="candidate-search"><span class="sr-only">搜索联系人</span><input name="q" maxlength="200" placeholder="搜索姓名、备注或来源会话" value="${esc(query)}"></label><label class="sr-only" for="dashboard-filter">筛选联系人</label><select id="dashboard-filter" name="selected">${Object.entries(
        {
          all: "全部联系人",
          customers: "商家档案",
          tasks: "有跟进任务",
          review: "需要确认",
          running: "整理中",
          unanalyzed: "尚未建档",
        },
      )
        .map(
          ([k, v]) =>
            `<option value="${k}" ${selected === k ? "selected" : ""}>${v}</option>`,
        )
        .join(
          "",
        )}</select><button type="submit">搜索</button></form><p id="dashboard-state" class="meta" role="status"></p></section><section class="card board-group" id="followup-group" aria-label="有跟进任务"><div class="group-heading"><div><h2>有跟进任务</h2><p id="followup-total" class="meta"></p></div><label class="sr-only" for="followup-filter">跟进范围</label><select id="followup-filter">${Object.entries(
        {
          all: "全部跟进",
          today: "今日到期",
          upcoming: "后续安排",
          waiting: "等待回复",
        },
      )
        .map(
          ([k, v]) =>
            `<option value="${k}" ${followup === k ? "selected" : ""}>${v}</option>`,
        )
        .join(
          "",
        )}</select></div>${columns}<div id="followup-rows" role="list"></div><div id="followup-pagination" class="toolbar progress-pagination"></div></section><section class="card board-group" id="other-group" aria-label="其他客户"><div class="group-heading"><div><h2>其他客户</h2><p id="other-total" class="meta"></p></div></div>${columns}<div id="dashboard-rows" role="list"></div><div id="dashboard-pagination" class="toolbar progress-pagination"></div></section></div>`;
  await load();
}
function contactRow(r, opened) {
  return `<article class="board-row" role="listitem" data-board-source="${esc(r.source_id)}"><div class="contact-cell" data-label="联系人">${r.document_id ? `<button class="contact-name" data-open-source="${esc(r.source_id)}">${esc(r.name)}</button>` : `<strong>${esc(r.name)}</strong>`}<p class="meta">${roles[r.relationship]}${r.paused_contact ? " · 已暂停联系" : ""}</p><p class="origin-line" title="${esc(r.origins.map((c) => c.title).join(" / "))}">${esc(r.origins.map((c) => (c.kind === "private" ? "私信" : c.title)).join(" / ") || "来源名称待同步")}</p></div><div class="insight-cell" data-label="档案摘要"><p class="contact-summary">${esc(r.summary || "分析后整理客户资料与备货线索。")}</p>${r.needs_update ? '<span class="meta">有新进展</span>' : ""}</div><div class="task-cell" data-label="待办与确认">${r.next_task ? `<p class="contact-summary">${esc(r.next_task.text)}</p><p class="meta">${r.next_task.state === "waiting" ? "等待回复" : r.next_task.due_date ? esc(r.next_task.due_date) : "待跟进"}</p>` : '<span class="meta">暂无待办</span>'}<div class="row-badges">${r.task_count ? `<button class="badge" data-open-source="${esc(r.source_id)}" data-open-tab="work">待办 ${r.task_count}</button>` : ""}${r.review_count ? `<button class="badge" data-open-source="${esc(r.source_id)}" data-open-tab="${r.review_tab}">待确认 ${r.review_count}</button>` : ""}</div></div><div class="analysis-cell" data-label="整理进度"><span class="job-state ${r.status === "running" ? "live" : ""}">${esc(r.status_label)}</span>${r.phase_label !== r.status_label ? `<p class="meta">${esc(r.phase_label)}</p>` : ""}${["running", "paused", "failed", "starting", "stopping"].includes(r.status) ? `<p class="meta">${esc(r.stage_detail)}</p>` : ""}${r.total_pages ? `<details data-task-details="${esc(r.source_id)}" ${opened.has(r.source_id) ? "open" : ""}><summary>查看进度</summary>${taskStages(r)}</details>` : ""}${r.error ? `<p class="meta error">${esc(errorText(r.error))}</p>` : ""}${r.action_hint ? `<p class="meta">${esc(r.action_hint)}</p>` : ""}</div><div class="board-actions" data-label="操作">${r.primary_action ? `<button data-progress-action="${esc(r.primary_action.action)}" data-source="${esc(r.source_id)}" ${r.primary_action.disabled ? "disabled" : ""}>${esc(r.primary_action.label)}</button>` : r.pending_label ? `<button disabled>${esc(r.pending_label)}</button>` : ""}<details class="contact-menu"><summary aria-label="管理${esc(r.name)}">•••</summary><div><button data-exclude-person="${esc(r.source_id)}">加入白名单</button></div></details></div></article>`;
}
function focusKey() {
  const el = document.activeElement;
  if (!el?.closest("#dashboard-view")) return null;
  return {
    id: el.id,
    source: el.dataset.source,
    action: el.dataset.progressAction,
    open: el.dataset.openSource,
  };
}
function restoreFocus(saved) {
  if (!saved) return;
  const next = saved.id
    ? document.getElementById(saved.id)
    : [...document.querySelectorAll("#dashboard-view button")].find(
        (b) =>
          (saved.source &&
            b.dataset.source === saved.source &&
            b.dataset.progressAction === saved.action) ||
          (saved.open && b.dataset.openSource === saved.open),
      );
  if (next && !next.disabled) next.focus({ preventScroll: true });
}
async function load() {
  const current = ++ticket;
  const data = await api(
    "dashboard?" +
      new URLSearchParams({
        q: query,
        selected,
        page,
        followup,
        followup_page: followupPage,
      }),
  );
  if (!active() || current !== ticket || !$("#dashboard-view")) return;
  page = data.page;
  followupPage = data.followups.page;
  const focus = focusKey();
  const opened = new Set(
    [...document.querySelectorAll("[data-task-details][open]")].map(
      (d) => d.dataset.taskDetails,
    ),
  );
  $("#dashboard-metrics").innerHTML = Object.entries({
    all: ["工作联系人", data.counts.contacts],
    customers: ["商家档案", data.counts.customers],
    tasks: ["待跟进客户", data.counts.tasks],
    running: ["正在整理", data.counts.running],
  })
    .map(
      ([key, [label, n]]) =>
        `<button class="metric ${selected === key ? "selected" : ""}" data-board-filter="${key}"><span>${label}</span><strong>${n}</strong></button>`,
    )
    .join("");
  const a = data.automation;
  $("#dashboard-automation").innerHTML =
    `<span class="meta">${a.enabled ? "自动整理已开启" : "自动整理已暂停"}</span><button id="automation-toggle" data-enabled="${!a.enabled}">${a.enabled ? "暂停自动整理" : "开启自动整理"}</button><button id="dashboard-refresh">刷新</button>`;
  const gates = {
    paused: "可逐人开始分析，也可开启自动整理。",
    no_background:
      "当前为手动服务，可逐人分析；自动运行请使用 wechat-agent start。",
    manual_mode: "当前为手动模式，可逐人分析。",
    blocked_policy: "请在设置中开启文本分析授权。",
    blocked_credentials: "请在设置中配置 DeepSeek key。",
    awaiting_account: "请在设置中绑定工作微信。",
  };
  $("#dashboard-state").textContent =
    `${data.matched_total} 位联系人 · 每组20位 · 白名单已排除。${a.gate ? gates[a.gate] || errorText(a.gate) : "后台会持续更新客户资料。"}`;
  $("#other-total").textContent = `${data.total} 位 · 暂无可执行跟进任务`;
  $("#dashboard-rows").innerHTML =
    data.items.map((r) => contactRow(r, opened)).join("") ||
    '<div class="empty"><h3>没有匹配联系人</h3><p>可清空筛选，或到设置检查微信接入与白名单。</p></div>';
  $("#dashboard-pagination").innerHTML =
    `<button id="board-prev" ${page === 1 ? "disabled" : ""}>上一页</button><span class="meta">第 ${page} / ${data.pages} 页</span><button id="board-next" ${page === data.pages ? "disabled" : ""}>下一页</button>`;
  const lane = data.followups;
  $("#followup-total").textContent = `${lane.total} 位客户有明确跟进任务`;
  $("#followup-rows").innerHTML =
    lane.items.map((r) => contactRow(r, opened)).join("") ||
    '<div class="lane-empty"><p>当前没有需要跟进的客户</p><small>有明确依据的任务会出现在这里。</small></div>';
  $("#followup-pagination").innerHTML =
    lane.pages > 1
      ? `<button id="followup-prev" ${followupPage === 1 ? "disabled" : ""}>上一组</button><span class="meta">${followupPage}/${lane.pages}</span><button id="followup-next" ${followupPage === lane.pages ? "disabled" : ""}>下一组</button>`
      : "";
  restoreFocus(focus);
}
async function submit(source, action) {
  if (pending.has(source) && action !== "pause") return;
  pending.add(source);
  notice(
    action === "pause"
      ? "正在暂停该客户…"
      : "正在整理，进度会持续更新；可在该行暂停。",
  );
  try {
    const result = await api("jobs/command", { source_id: source, action });
    await renderDashboard();
    notice(
      {
        completed: "分析完成，档案与跟进已更新。",
        queued: "已加入队列，将优先整理该联系人。",
        paused: "进度已保存，可继续分析。",
        stopping: "当前请求结束后停止，分册会保留。",
        running: "正在整理，无需重复开始。",
        starting: "任务正在启动。",
        ready: "等待整理，可开始或继续分析。",
      }[result.execution] || "状态已更新。",
    );
  } finally {
    pending.delete(source);
  }
}
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "dashboard-search") return;
  e.preventDefault();
  const f = new FormData(e.target);
  query = f.get("q").trim();
  followupPage = 1;
  selected = f.get("selected");
  page = 1;
  try {
    await load();
  } catch (error) {
    notice(error.message);
  }
});
document.addEventListener("change", async (e) => {
  if (!["dashboard-filter", "followup-filter"].includes(e.target.id)) return;
  if (e.target.id === "dashboard-filter") {
    selected = e.target.value;
    page = 1;
    followupPage = 1;
  } else {
    followup = e.target.value;
    followupPage = 1;
  }
  try {
    await load();
  } catch (error) {
    notice(error.message);
  }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || !active()) return;
  if (
    !b.dataset.progressAction &&
    !b.dataset.excludePerson &&
    !b.dataset.boardFilter &&
    ![
      "automation-toggle",
      "dashboard-refresh",
      "board-prev",
      "board-next",
      "followup-prev",
      "followup-next",
    ].includes(b.id)
  )
    return;
  b.disabled = true;
  try {
    if (b.dataset.progressAction) {
      await submit(b.dataset.source, b.dataset.progressAction);
      return;
    }
    if (b.dataset.excludePerson) {
      await api("whitelist", {
        entity: "people",
        id: b.dataset.excludePerson,
        excluded: true,
      });
      await load();
      notice("已加入白名单，从大屏与跟进栏移除；原始记录保留。");
      return;
    }
    if (b.dataset.boardFilter) {
      selected = b.dataset.boardFilter;
      page = 1;
      $("#dashboard-filter").value = selected;
      $("#dashboard-filter").dispatchEvent(
        new Event("change", { bubbles: true }),
      );
      return;
    }
    if (b.id === "automation-toggle")
      await api("automation", { enabled: b.dataset.enabled === "true" });
    if (b.id === "dashboard-refresh") await api("queue/refresh", {});
    if (b.id === "board-prev") page--;
    if (b.id === "board-next") page++;
    if (b.id === "followup-prev") followupPage--;
    if (b.id === "followup-next") followupPage++;
    await load();
  } catch (error) {
    notice(error.message);
  } finally {
    if (b.isConnected) b.disabled = false;
  }
});
setInterval(() => {
  if (active() && !polling) {
    polling = true;
    load()
      .catch(() => {})
      .finally(() => (polling = false));
  }
}, 5000);
