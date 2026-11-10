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
    `<div class="toolbar"><div class="segments" aria-label="白名单类型"><button data-white-entity="people" aria-pressed="${entity === "people"}">人物</button><button data-white-entity="conversations" aria-pressed="${entity === "conversations"}">会话</button></div><span class="meta">${data.total} 个免跟进对象</span><button id="white-add-toggle">${adding ? "收起添加入口" : "添加白名单"}</button></div><form id="white-search" class="search-form"><label class="candidate-search"><span class="sr-only">搜索白名单</span><input name="q" value="${esc(query)}" placeholder="搜索白名单中的姓名或会话"></label><button>搜索</button></form>${adding ? `<section class="white-add"><h3>选择需要排除的${entity === "people" ? "联系人" : "会话"}</h3><form id="white-add-search" class="search-form"><label class="candidate-search"><span class="sr-only">查找添加对象</span><input name="q" value="${esc(addQuery)}" placeholder="备注、名称或微信 ID"></label><button>查找</button></form><div id="white-candidates">正在读取…</div></section>` : ""}<div id="white-rows">${data.items.map((r) => `<article class="white-row"><div><strong>${esc(r.name)}</strong><p class="meta">${entity === "people" ? "免跟进人物" : r.kind === "group" ? "免跟进群聊" : "免跟进私信"}</p></div><button data-white-restore="${esc(r.id)}">恢复跟进</button></article>`).join("") || '<p class="empty">当前白名单为空。</p>'}</div><div class="toolbar"><button id="white-prev" ${page === 1 ? "disabled" : ""}>上一页白名单</button><span class="meta">第 ${page} / ${data.pages} 页 · 每页50条</span><button id="white-next" ${data.has_more ? "" : "disabled"}>下一页白名单</button></div>`;
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
          `<article class="white-row"><div><strong>${esc(r.name)}</strong><p class="meta">${entity === "conversations" ? (r.kind === "group" ? "群聊" : "私信") : "工作联系人"}</p></div><button data-white-add="${esc(r.id)}">加入白名单</button></article>`,
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
