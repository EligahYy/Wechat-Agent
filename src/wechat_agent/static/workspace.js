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
import { renderDashboard, selectDashboard } from "./workspace/dashboard.js";
import { customerHTML, evidence, mediaControls } from "./workspace/customer.js";
import { closeImage } from "./workspace/media.js";
function route() {
  const requested =
    new URLSearchParams(location.search).get("view") ||
    new URLSearchParams(location.search).get("page") ||
    "dashboard";
  if (requested === "review") selectDashboard("review");
  if (requested === "customers") selectDashboard("customers");
  if (["scope", "whitelist"].includes(requested))
    history.replaceState({}, "", "/workspace?view=settings#whitelist");
  return ["settings", "scope", "whitelist"].includes(requested)
    ? "settings"
    : "dashboard";
}
let view = route(),
  selected,
  focusBefore,
  timelineQuery = "";
async function refresh() {
  document
    .querySelectorAll("nav button")
    .forEach((b) =>
      b.setAttribute(
        "aria-current",
        b.dataset.view === view ? "page" : "false",
      ),
    );
  $("#title").textContent = view === "settings" ? "设置与接入" : "数据大屏";
  await (view === "settings" ? renderSettings() : renderDashboard());
}
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
      const source = selected.source_id;
      await api("command", {
        source_id: selected.source_id,
        version: selected.version,
        operation: "followup",
        value,
      });
      await api("queue/refresh", {});
      close();
      await refresh();
      await openDetail(source);
      detailTab("journal");
      await loadJournal();
      $("#detail-status").textContent = "人工跟进已保存。";
    } catch (error) {
      $("#detail-status").textContent = error.message;
      if (b.isConnected) b.disabled = false;
    }
    return;
  }
});

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
async function openDetail(source, initial = "overview") {
  selected = await api(
    "customer?" + new URLSearchParams({ source_id: source }),
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
  if (focusBefore?.isConnected) focusBefore.focus({ preventScroll: true });
  else
    [...document.querySelectorAll("[data-open-source]")]
      .find((b) => b.dataset.openSource === selected?.source_id)
      ?.focus({ preventScroll: true });
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  try {
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
      await api("whitelist", {
        entity: "people",
        id: selected.source_id,
        excluded: true,
      });
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
    if (b.dataset.view) {
      view = b.dataset.view;
      history.pushState({}, "", "/workspace?view=" + view);
      await refresh();
    }
    if (b.dataset.openSource) {
      b.disabled = true;
      await openDetail(b.dataset.openSource, b.dataset.openTab || "overview");
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

addEventListener("popstate", () => {
  view = route();
  if ($("dialog").open) close();
  refresh().catch((e) => notice(e.message));
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
