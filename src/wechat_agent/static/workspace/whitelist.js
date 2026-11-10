import { $, esc, api, notice } from "./client.js";
let entity = "people",
  query = "",
  page = 1,
  addQuery = "",
  addPage = 1,
  ticket = 0,
  adding = false;
const active = () => !!$("#whitelist-manager");
export async function renderWhitelist() {
  if (!active()) return;
  const current = ++ticket;
  const data = await api(
    "whitelist?" +
      new URLSearchParams({ entity, q: query, scope: "archive", page }),
  );
  if (!active() || current !== ticket) return;
  page = data.page;
  $("#whitelist-manager").innerHTML =
    `<div class="toolbar"><div class="segments" aria-label="白名单类型"><button data-white-entity="people" aria-pressed="${entity === "people"}">人物 ${data.counts.people}</button><button data-white-entity="groups" aria-pressed="${entity === "groups"}">群聊会话 ${data.counts.groups}</button></div><span class="meta">${data.total} 个${entity === "people" ? "免跟进人物" : "免跟进群聊"}</span><button id="white-add-toggle">${adding ? "收起添加入口" : "添加白名单"}</button></div><p class="meta">${entity === "people" ? "人物包含手动排除和随群免跟进的成员；私信统一在这里管理。" : "群聊和群内已识别成员一并免跟进；新发现的成员自动沿用，原始记录保留。"}</p><form id="white-search" class="search-form"><label class="candidate-search"><span class="sr-only">搜索白名单</span><input name="q" value="${esc(query)}" placeholder="搜索白名单中的姓名或会话"></label><button>搜索</button></form>${adding ? `<section class="white-add"><h3>选择需要排除的${entity === "people" ? "联系人" : "群聊会话"}</h3><form id="white-add-search" class="search-form"><label class="candidate-search"><span class="sr-only">查找添加对象</span><input name="q" value="${esc(addQuery)}" placeholder="备注、名称或微信 ID"></label><button>查找</button></form><div id="white-candidates">正在读取…</div></section>` : ""}<div id="white-rows">${data.items.map((r) => `<article class="white-row"><div><strong>${esc(r.name)}</strong><p class="meta">${entity === "people" ? (r.groups.length ? "人物 · 随群免跟进" : "人物 · 手动免跟进") : "群聊会话 · 群成员一并免跟进"}</p>${entity === "people" && r.groups.length ? `<p class="meta">来自群：${esc(r.groups.map((g) => g.name).join("、"))}${r.manual ? " · 同时有手动排除" : ""}</p>` : entity === "groups" && !r.pending ? `<p class="meta">已识别 ${r.members} 位成员随群免跟进</p>` : ""}${r.pending ? '<p class="meta">群聊尚未同步，排除配置已保留。</p>' : r.allowlisted === 0 ? '<p class="meta">会话已暂停采集，恢复跟进前需先恢复采集。</p>' : ""}<details><summary>微信 ID</summary><p class="meta">${esc(r.source_id)}</p></details></div>${entity === "people" && r.groups.length ? `<button data-white-group="${esc(r.groups[0].source_id)}">管理关联群</button>` : `<button data-white-restore="${esc(r.id)}">恢复跟进</button>`}</article>`).join("") || '<p class="empty">当前白名单为空。</p>'}</div><div class="toolbar"><button id="white-prev" ${page === 1 ? "disabled" : ""}>上一页白名单</button><span class="meta">第 ${page} / ${data.pages} 页 · 每页50条</span><button id="white-next" ${data.has_more ? "" : "disabled"}>下一页白名单</button></div>`;
  if (adding) await loadCandidates();
}
async function loadCandidates() {
  const currentEntity = entity,
    currentQuery = addQuery;
  const data = await api(
    "whitelist?" +
      new URLSearchParams({
        entity,
        q: addQuery,
        scope: "customer",
        page: addPage,
      }),
  );
  if (
    !$("#white-candidates") ||
    currentEntity !== entity ||
    currentQuery !== addQuery
  )
    return;
  addPage = data.page;
  $("#white-candidates").innerHTML =
    data.items
      .map(
        (r) =>
          `<article class="white-row"><div><strong>${esc(r.name)}</strong><p class="meta">${entity === "groups" ? "群聊会话" : "工作联系人"}</p></div><button data-white-add="${esc(r.id)}">加入白名单</button></article>`,
      )
      .join("") || '<p class="meta">没有匹配对象。</p>';
  $("#white-candidates").innerHTML +=
    `<div class="toolbar"><button id="white-add-prev" ${addPage === 1 ? "disabled" : ""}>上一页候选</button><span class="meta">第 ${addPage} / ${data.pages} 页</span><button id="white-add-next" ${data.has_more ? "" : "disabled"}>下一页候选</button></div>`;
}
document.addEventListener("submit", async (e) => {
  if (!["white-search", "white-add-search"].includes(e.target.id)) return;
  e.preventDefault();
  const q = new FormData(e.target).get("q").trim();
  if (e.target.id === "white-search") {
    query = q;
    page = 1;
  } else {
    addQuery = q;
    addPage = 1;
  }
  try {
    await renderWhitelist();
  } catch (error) {
    notice(error.message);
  }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || !active()) return;
  if (
    !b.dataset.whiteEntity &&
    !b.dataset.whiteAdd &&
    !b.dataset.whiteRestore &&
    !b.dataset.whiteGroup &&
    ![
      "white-add-toggle",
      "white-prev",
      "white-next",
      "white-add-prev",
      "white-add-next",
    ].includes(b.id)
  )
    return;
  b.disabled = true;
  try {
    if (b.dataset.whiteEntity) {
      entity = b.dataset.whiteEntity;
      query = "";
      page = 1;
      addQuery = "";
      addPage = 1;
    }
    if (b.dataset.whiteGroup) {
      entity = "groups";
      query = b.dataset.whiteGroup;
      page = 1;
      adding = false;
    }
    if (b.id === "white-add-toggle") adding = !adding;
    if (b.id === "white-prev") page--;
    if (b.id === "white-next") page++;
    if (b.id === "white-add-prev") addPage--;
    if (b.id === "white-add-next") addPage++;
    if (b.dataset.whiteAdd || b.dataset.whiteRestore) {
      await api("whitelist", {
        entity,
        id: b.dataset.whiteAdd || b.dataset.whiteRestore,
        excluded: !!b.dataset.whiteAdd,
      });
      notice(
        b.dataset.whiteAdd
          ? "已加入白名单，原始资料保留。"
          : "已恢复跟进，回到数据大屏查看。",
      );
    }
    await renderWhitelist();
  } catch (error) {
    notice(error.message);
  } finally {
    if (b.isConnected) b.disabled = false;
  }
});
