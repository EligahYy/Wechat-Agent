import { $, esc, api, notice } from "./client.js";
let entity = "conversations",
  scope = "customer",
  kind = "all",
  page = 1,
  query = "",
  selected = new Set(),
  rows = [],
  ticket = 0,
  undoId;
const active = () => $("[data-view=scope][aria-current=page]");
export async function renderScope() {
  const current = ++ticket;
  const params = new URLSearchParams({ q: query, scope, page, kind });
  const data = await api(
    entity === "people"
      ? "/api/crm/people?" + params
      : "/api/crm/exemptions?" + params,
  );
  if (!active() || current !== ticket) return;
  if (data.pages && page > data.pages) {
    page = data.pages;
    return renderScope();
  }
  page = data.page;
  rows = data.items;
  $("#content").innerHTML =
    `<section id="scope-view" class="card"><h2>白名单内，仅归档不做客户跟进</h2><p class="muted">排除整个会话，或排除某个人。原始记录保留；人物排除也适用于其在其他群中的客户身份。</p><div class="toolbar segments spaced" role="tablist" aria-label="跟进范围"><button role="tab" data-scope="customer" aria-selected="${scope === "customer"}">正常跟进</button><button role="tab" data-scope="archive" aria-selected="${scope === "archive"}">白名单 · 免跟进</button></div><div class="toolbar"><div class="segments"><button data-scope-entity="conversations" aria-pressed="${entity === "conversations"}">会话</button><button data-scope-entity="people" aria-pressed="${entity === "people"}">人物</button></div>${
      entity === "conversations"
        ? `<div class="segments">${Object.entries({
            all: "全部",
            private: "私信",
            group: "群聊",
          })
            .map(
              ([k, n]) =>
                `<button data-scope-kind="${k}" aria-pressed="${kind === k}">${n}</button>`,
            )
            .join("")}</div>`
        : ""
    }</div><form id="workspace-scope-search" class="toolbar"><label class="candidate-search">搜索${entity === "people" ? "人物" : "会话"}<input name="q" maxlength="200" value="${esc(query)}" placeholder="备注、名称或微信 ID"></label><button>搜索</button></form>${entity === "conversations" ? `<div class="toolbar"><button id="scope-page-select">勾选本页</button><button id="scope-clear-select">清空勾选</button><button id="scope-apply-selection" class="primary" ${selected.size ? "" : "disabled"}>${scope === "customer" ? "加入白名单" : "恢复跟进"}（${selected.size}）</button></div>` : ""}<div>${rows.map((r) => `<article class="scope-row">${entity === "conversations" ? `<input type="checkbox" aria-label="选择${esc(r.title)}" data-scope-select="${esc(r.id)}" ${selected.has(r.id) ? "checked" : ""}>` : ""}<div class="scope-name"><strong>${esc(r.title || r.name)}</strong><p class="meta">${entity === "conversations" ? `${r.kind === "group" ? "群聊" : "私信"} · ${r.messages} 条 · ` : ""}${scope === "archive" ? "仅归档" : "正常跟进"}</p><details><summary>微信 ID</summary><small>${esc(r.source_id)}</small></details></div><button data-scope-row="${esc(r.id)}">${scope === "customer" ? "加入白名单" : "恢复跟进"}</button></article>`).join("") || `<div class="empty"><p>${scope === "archive" ? "白名单为空" : "未找到匹配来源"}</p></div>`}</div><div class="toolbar spaced"><button id="scope-prev" ${page > 1 ? "" : "disabled"}>上一页范围</button><span>第 ${page} 页 · 共 ${data.total} 个 · 每页最多50条</span><button id="scope-next" ${data.has_more ? "" : "disabled"}>下一页范围</button></div>${undoId ? '<button id="scope-undo">撤销上次会话范围操作</button>' : ""}</section>`;
}
async function change(ids) {
  if (entity === "people")
    await api("/api/crm/people/" + encodeURIComponent(ids[0]) + "/exclusion", {
      enabled: scope === "customer",
    });
  else {
    const result = await api("/api/crm/exemptions", {
      conversation_ids: ids,
      enabled: scope === "customer",
    });
    undoId = result.undo_id;
  }
  selected.clear();
  await api("queue/refresh", {});
  await renderScope();
  notice(
    scope === "customer"
      ? "已加入白名单，保留原始记录。"
      : "已恢复跟进，后台会按当前授权处理。",
  );
}
document.addEventListener("submit", async (e) => {
  if (e.target.id !== "workspace-scope-search") return;
  e.preventDefault();
  query = new FormData(e.target).get("q").trim();
  page = 1;
  selected.clear();
  try {
    await renderScope();
  } catch (error) {
    notice(error.message);
  }
});
document.addEventListener("change", (e) => {
  if (!e.target.dataset.scopeSelect) return;
  e.target.checked
    ? selected.add(e.target.dataset.scopeSelect)
    : selected.delete(e.target.dataset.scopeSelect);
  const b = $("#scope-apply-selection");
  b.disabled = !selected.size;
  b.textContent = `${scope === "customer" ? "加入白名单" : "恢复跟进"}（${selected.size}）`;
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || !active()) return;
  if (
    !b.dataset.scope &&
    !b.dataset.scopeEntity &&
    !b.dataset.scopeKind &&
    !b.dataset.scopeRow &&
    ![
      "scope-prev",
      "scope-next",
      "scope-page-select",
      "scope-clear-select",
      "scope-apply-selection",
      "scope-undo",
    ].includes(b.id)
  )
    return;
  b.disabled = true;
  try {
    if (b.dataset.scope || b.dataset.scopeEntity || b.dataset.scopeKind) {
      scope = b.dataset.scope || scope;
      entity = b.dataset.scopeEntity || entity;
      kind = b.dataset.scopeKind || kind;
      page = 1;
      selected.clear();
    }
    if (b.id === "scope-prev") page--;
    if (b.id === "scope-next") page++;
    if (b.id === "scope-page-select") rows.forEach((r) => selected.add(r.id));
    if (b.id === "scope-clear-select") selected.clear();
    if (b.dataset.scopeRow) {
      await change([b.dataset.scopeRow]);
      return;
    }
    if (b.id === "scope-apply-selection") {
      await change([...selected]);
      return;
    }
    if (b.id === "scope-undo") {
      await api("/api/crm/exemptions/undo", { event_id: undoId });
      undoId = null;
      await api("queue/refresh", {});
    }
    await renderScope();
  } catch (error) {
    notice(error.message);
    if (b.isConnected) b.disabled = false;
  }
});
