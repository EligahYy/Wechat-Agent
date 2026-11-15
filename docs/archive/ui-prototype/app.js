/* Interactive design prototype. No external requests and no real model calls. */
(() => {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const esc = (value) =>
    String(value ?? "").replace(
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
  const icons = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
    workspace:
      '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M3 9h18M9 9v12"/>',
    settings:
      '<path d="m9 3-.7 2.4-2.4.7L4 5l-2 3 1.8 1.8-.1 2.5L2 14l2 3 2.4-.5 2 1.4L9 21h4l.7-2.7 2.1-1.3 2.3.5 2-3-1.7-1.7-.1-2.6L20 8l-2-3-2.2 1.1-2.4-.7L13 3Z"/><circle cx="11" cy="12" r="3"/>',
    theme: '<path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    arrow: '<path d="m9 5 7 7-7 7"/>',
    back: '<path d="m15 5-7 7 7 7"/>',
    close: '<path d="m6 6 12 12M18 6 6 18"/>',
    refresh:
      '<path d="M20 7v5h-5M4 17v-5h5M5.1 7a8 8 0 0 1 13.2-2L20 7M4 17l1.7 2A8 8 0 0 0 19 17"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    source:
      '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/>',
    copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    image:
      '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 3-4 6 7"/>',
    file: '<path d="M14 2H5v20h14V7Z"/><path d="M14 2v5h5M8 12h8M8 16h6"/>',
    people:
      '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M17 5a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 5"/>',
    shield:
      '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
    play: '<path d="m9 5 10 7-10 7Z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    edit: '<path d="m15 4 5 5-11 11H4v-5ZM13 6l5 5"/>',
  };
  const icon = (name, cls = "") =>
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.info}</svg>`;
  const key = "eu-workspace-prototype-v1";
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(key) || "{}");
  } catch {
    /* Storage is optional. */
  }
  const state = {
    contacts: structuredClone(window.DEMO.contacts),
    tab: "merchants",
    query: "",
    filter: "全部",
    page: 1,
    selection: new Set(),
    theme: saved.theme || "system",
    daily: saved.daily ?? true,
    time: saved.time || "08:30",
    timeDraft: null,
    roles: saved.roles || {},
    numbers: saved.numbers || {},
    edits: saved.edits || {},
    supplements: saved.supplements || {},
    run: saved.run || { status: "idle", queue: [], done: 0, stage: 0 },
    detail: null,
    detailTab: "overview",
    timelineQuery: "",
  };
  state.contacts.forEach((c) => {
    if (saved.updates?.[c.id]) Object.assign(c, saved.updates[c.id]);
    if (state.roles[c.id]) {
      c.role = state.roles[c.id];
      c.manual = true;
    }
  });
  if (state.run.status === "running") state.run.status = "stopped";
  let runTimer, toastTimer;
  const contact = (id) => state.contacts.find((c) => c.id === id);
  const merchants = () => state.contacts.filter((c) => c.role === "商家");
  const persist = () => {
    try {
      localStorage.setItem(
        key,
        JSON.stringify({
          theme: state.theme,
          daily: state.daily,
          time: state.time,
          roles: state.roles,
          numbers: state.numbers,
          edits: state.edits,
          supplements: state.supplements,
          run: state.run,
          updates: Object.fromEntries(
            state.contacts.map((c) => [
              c.id,
              {
                complete: c.complete,
                fresh: !!c.fresh,
                updated: c.updated,
                summary: c.summary,
                tags: c.tags,
              },
            ]),
          ),
        }),
      );
    } catch {
      /* Private browsing may disable storage. */
    }
  };
  const isDark = () =>
    state.theme === "dark" ||
    (state.theme === "system" &&
      matchMedia("(prefers-color-scheme: dark)").matches);
  function applyTheme() {
    document.documentElement.dataset.theme = isDark() ? "dark" : "light";
    const dark = isDark();
    $("#theme-label").textContent = dark ? "切换浅色外观" : "切换深色外观";
    const toggle = $('[data-action="theme-toggle"]');
    toggle.setAttribute("aria-pressed", String(dark));
    toggle.title = $("#theme-label").textContent;
    document.body.style.backgroundColor = getComputedStyle(
      document.documentElement,
    ).getPropertyValue("--bg");
    document.documentElement.style.colorScheme = dark ? "dark" : "light";
  }
  function toast(message) {
    clearTimeout(toastTimer);
    const el = $("#toast");
    el.textContent = message;
    el.hidden = false;
    toastTimer = setTimeout(() => {
      el.hidden = true;
    }, 3600);
  }
  const tag = (text, kind = "") =>
    `<span class="state-tag ${kind}">${esc(text)}</span>`;
  const roleKinds = {
    商家: "merchant",
    服务商: "provider",
    平台: "platform",
    待识别: "unknown",
  };
  const roleTag = (role) =>
    `<span class="role-tag role-${roleKinds[role] || "self"}">${esc(role)}</span>`;
  const humanTime = () =>
    new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date());
  const runLabels = {
    idle: "资料已归档，等你开始整理",
    running: "正在按商家整理资料",
    stopped: "本次整理已停止",
    completed: "本次资料整理已完成",
  };
  const runStages = ["读取相关历史", "按时间整理资料", "归纳档案与来源"];
  const runRemaining = () =>
    state.run.queue
      .slice(state.run.done)
      .filter((id) => contact(id)?.role === "商家").length;
  function runAction() {
    if (state.run.status === "running") return ["stop", "停止本次", "stop"];
    if (state.run.status === "stopped" && runRemaining())
      return ["resume", "继续本次", "play"];
    return ["sync", "同步并整理", "refresh"];
  }
  function renderRunStrip() {
    const r = state.run;
    const detail =
      r.status === "running"
        ? `${contact(r.queue[r.done])?.name || ""} · ${runStages[r.stage]} · 已完成 ${r.done} / ${r.queue.length} 位`
        : r.status === "stopped"
          ? `已完成 ${r.done} 位，剩余 ${runRemaining()} 位；已完成资料保留。`
          : r.status === "completed"
            ? `已完成 ${r.done} 位商家的资料更新 · ${r.finished || ""} 北京时间`
            : `每日 ${state.time} 北京时间${state.daily ? "自动整理" : "自动整理已关闭"}`;
    return `<div class="run-strip ${r.status === "running" ? "running" : ""}" id="run-strip"><div class="run-strip-left"><div class="run-icon">${icon(r.status === "completed" ? "check" : r.status === "running" ? "refresh" : "clock")}</div><div><strong>${runLabels[r.status]}</strong><p>${esc(detail)}</p></div></div><button class="text-button" data-action="run-detail">查看进度 ${icon("arrow")}</button></div>`;
  }
  function render(navigation = false) {
    const settings = location.hash === "#settings";
    $$("[data-nav]").forEach((a) => {
      if (a.dataset.nav === (settings ? "settings" : "workspace"))
        a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = `${settings ? "设置" : "工作台"} · 半托管欧区备货用户助手`;
    $("#view").innerHTML = settings ? renderSettings() : renderWorkspace();
    bindListInput();
    updateSelectionUI();
    placeWorkspaceIndicator();
    placeRoleFilterIndicator();
    placeNavIndicator(navigation);
    if (navigation && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      $("#view").animate(
        [
          { opacity: 0, transform: "translateY(9px)" },
          { opacity: 1, transform: "none" },
        ],
        { duration: 300, easing: "cubic-bezier(.22,1,.36,1)" },
      );
  }
  function placeRoleFilterIndicator(previous = null) {
    const group = $(".filter-group"),
      selected = group?.querySelector("[aria-pressed=true]");
    if (!selected) return;
    group.classList.add("role-filter-animated");
    group.querySelector(".role-filter-indicator")?.remove();
    const pill = document.createElement("span");
    pill.className = "role-filter-indicator";
    pill.setAttribute("aria-hidden", "true");
    pill.style.left = selected.offsetLeft + "px";
    pill.style.width = selected.offsetWidth + "px";
    pill.style.top = selected.offsetTop + "px";
    pill.style.height = selected.offsetHeight + "px";
    group.prepend(pill);
    if (previous && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      pill.animate(
        [
          {
            transform: `translateX(${previous.x - selected.offsetLeft}px) scaleX(${previous.w / selected.offsetWidth})`,
          },
          { transform: "none" },
        ],
        { duration: 320, easing: "cubic-bezier(.22,1,.36,1)" },
      );
  }
  function placeNavIndicator(animate = false) {
    const nav = $(".sidebar nav"),
      selected = nav.querySelector("[aria-current=page]");
    if (!selected) return;
    let indicator = nav.querySelector(".nav-active-glass");
    const old = indicator
      ? {
          y:
            indicator.getBoundingClientRect().top -
            nav.getBoundingClientRect().top,
          h: indicator.getBoundingClientRect().height,
        }
      : null;
    if (!indicator) {
      indicator = document.createElement("span");
      indicator.className = "nav-active-glass";
      indicator.setAttribute("aria-hidden", "true");
      nav.prepend(indicator);
    }
    indicator.getAnimations().forEach((a) => a.cancel());
    indicator.style.top = selected.offsetTop + "px";
    indicator.style.height = selected.offsetHeight + "px";
    if (
      animate &&
      old &&
      !matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      indicator.animate(
        [
          {
            transform: `translateY(${old.y - selected.offsetTop}px) scaleY(${old.h / selected.offsetHeight})`,
          },
          { transform: "none" },
        ],
        { duration: 360, easing: "cubic-bezier(.22,1,.36,1)" },
      );
  }
  function placeWorkspaceIndicator(previous) {
    const list = $(".workspace-tabs"),
      selected = list?.querySelector("[aria-selected=true]");
    if (!selected) return;
    list.querySelector(".workspace-indicator")?.remove();
    const line = document.createElement("span");
    line.className = "workspace-indicator";
    line.setAttribute("aria-hidden", "true");
    line.style.left = selected.offsetLeft + "px";
    line.style.width = selected.offsetWidth + "px";
    list.append(line);
    if (previous && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      line.animate(
        [
          {
            transform: `translateX(${previous.x - selected.offsetLeft}px) scaleX(${previous.w / selected.offsetWidth})`,
          },
          { transform: "none" },
        ],
        { duration: 340, easing: "cubic-bezier(.22,1,.36,1)" },
      );
  }
  function renderWorkspace() {
    const [cmd, label, ico] = runAction();
    return `<header class="page-head"><div><h1>工作台</h1></div><div class="head-actions"><button class="btn btn--primary" data-action="run-command" data-command="${cmd}">${icon(ico)}${label}</button><button class="btn" data-action="run-detail">整理记录</button></div></header>
      <div class="workspace-tabs" role="tablist" aria-label="工作台视图"><button id="tab-merchants" role="tab" aria-selected="${state.tab === "merchants"}" aria-controls="workspace-panel" tabindex="${state.tab === "merchants" ? 0 : -1}" data-action="workspace-tab" data-tab="merchants">商家档案<span class="tab-count">${merchants().length}</span></button><button id="tab-contacts" role="tab" aria-selected="${state.tab === "contacts"}" aria-controls="workspace-panel" tabindex="${state.tab === "contacts" ? 0 : -1}" data-action="workspace-tab" data-tab="contacts">全部联系人<span class="tab-count">${state.contacts.length}</span></button></div>
      ${renderRunStrip()}<section id="workspace-panel" role="tabpanel" aria-labelledby="tab-${state.tab}" tabindex="0"><div class="list-surface"><div class="list-toolbar"><label class="search-field"><span class="search-caption">${state.tab === "merchants" ? "搜索商家" : "搜索联系人"}</span>${icon("search")}<input id="list-search" type="search" placeholder="${state.tab === "merchants" ? "搜索姓名、备注或来源群名" : "搜索姓名、备注、微信 ID 或群名"}" aria-label="${state.tab === "merchants" ? "搜索商家档案" : "搜索全部联系人"}" value="${esc(state.query)}"><button type="button" class="search-clear" data-action="clear-search" data-target="list-search" aria-label="清空搜索" ${state.query ? "" : "hidden"}>${icon("close")}</button></label>${renderFilters()}</div><div id="list-region">${renderList()}</div></div></section>`;
  }
  function renderFilters() {
    if (state.tab === "contacts")
      return `<div class="filter-group" aria-label="身份筛选">${["全部", "商家", "服务商", "平台", "待识别"].map((f) => `<button class="filter-button" aria-pressed="${state.filter === f}" data-action="filter" data-filter="${f}">${f}<span>${f === "全部" ? state.contacts.length : state.contacts.filter((c) => c.role === f).length}</span></button>`).join("")}</div>`;
    return `<div class="filter-select"><span class="search-caption" id="filter-label">资料状态</span><button id="filter-trigger" class="glass-select" aria-haspopup="listbox" aria-expanded="false" aria-controls="filter-menu" popovertarget="filter-menu">${state.filter === "全部" ? "全部资料" : state.filter}${icon("arrow")}</button><div id="filter-menu" popover role="listbox" aria-labelledby="filter-label">${["全部", "待更新", "待整理"].map((f) => `<button role="option" aria-selected="${state.filter === f}" data-action="filter" data-filter="${f}">${f === "全部" ? "全部资料" : f}${state.filter === f ? icon("check") : ""}</button>`).join("")}</div></div>`;
  }
  function filtered() {
    const q = state.query.trim().toLowerCase();
    return (state.tab === "merchants" ? merchants() : state.contacts).filter(
      (c) => {
        if (
          q &&
          ![c.name, c.remark, c.alias, c.wxid, ...c.sources].some((v) =>
            v.toLowerCase().includes(q),
          )
        )
          return false;
        if (state.tab === "contacts")
          return state.filter === "全部" || c.role === state.filter;
        return (
          state.filter === "全部" ||
          (state.filter === "待更新" && c.complete && c.fresh) ||
          (state.filter === "待整理" && !c.complete)
        );
      },
    );
  }
  function renderList() {
    const all = filtered();
    const pages = Math.max(1, Math.ceil(all.length / 20));
    state.page = Math.min(state.page, pages);
    const rows = all.slice((state.page - 1) * 20, state.page * 20);
    const meta = `<div class="list-meta"><span>${all.length} 位${state.tab === "merchants" ? "商家" : "联系人"}</span><span>·</span><span>${state.tab === "merchants" ? "已按最近业务沟通排列" : "身份由你最终确认"}</span><span class="meta-spacer"></span><span>每页 20 位</span></div>`;
    const selection =
      state.tab === "contacts"
        ? `<div class="selection-slot" data-active="${!!state.selection.size}" aria-hidden="${!state.selection.size}" ${state.selection.size ? "" : "inert"}><div class="selection-reveal"><div class="selection-bar"><strong>已选 ${state.selection.size} 位联系人</strong><button class="btn btn--primary selection-action" data-action="batch-role">设置身份</button><button class="text-button" data-action="clear-selection">清空</button></div></div></div>`
        : "";
    const empty = `<div class="empty">${icon("search")}<h2>没有找到匹配的联系人</h2><p>试试姓名、微信 ID 或来源群名，也可以清除筛选后查看。</p><button class="btn" data-action="reset-filter">清除筛选</button></div>`;
    const table =
      state.tab === "merchants"
        ? `<table class="merchant-table"><caption class="sr-only">商家档案列表</caption><thead><tr><th scope="col">联系人</th><th scope="col">货品与路线</th><th scope="col">当前沟通</th><th scope="col">资料更新</th><th scope="col"><span class="sr-only">查看档案</span></th></tr></thead><tbody>${rows.map((c) => `<tr><td><div class="person-cell"><span class="avatar ${c.fresh ? "blue" : ""}">${esc(c.name.slice(-2))}</span><div><button class="person-name" data-action="detail" data-id="${c.id}">${esc(c.name)}</button><div class="person-meta">${c.sources.length > 1 ? `私信 + ${c.sources.length - 1} 个群聊` : "私信"}</div></div></div></td><td><p class="cell-title">${esc(c.goods || "货品待整理")}</p><p class="cell-sub">${esc(c.route || "路线待整理")}</p></td><td>${(c.tags.length ? c.tags : ["待整理"]).map((t) => tag(t, t === "暂无新需求记录" ? "neutral" : t === "备货中" ? "positive" : "")).join(" ")}<p class="cell-summary">${esc(c.summary)}</p></td><td class="update-cell">${c.complete && c.fresh ? '<span class="pending-update">待更新</span>' : ""}${esc(c.updated || "尚未整理")}</td><td><button class="row-open" aria-label="查看${esc(c.name)}的档案" data-action="detail" data-id="${c.id}">${icon("arrow")}</button></td></tr>`).join("")}</tbody></table>`
        : `<table class="merchant-table contacts-table"><caption class="sr-only">统一联系人列表</caption><thead><tr><th scope="col"><label class="checkbox-wrap"><input class="checkbox" type="checkbox" id="select-page" aria-label="选择本页联系人" ${rows.length && rows.every((c) => state.selection.has(c.id)) ? "checked" : ""}></label></th><th scope="col">联系人</th><th scope="col">身份</th><th scope="col">关联来源</th><th scope="col"><span class="sr-only">操作</span></th></tr></thead><tbody>${rows.map((c) => `<tr><td><label class="checkbox-wrap"><input class="checkbox" type="checkbox" data-contact-select="${c.id}" aria-label="选择${esc(c.name)}" ${state.selection.has(c.id) ? "checked" : ""}></label></td><td><div class="person-cell"><span class="avatar">${esc(c.name.slice(-2))}</span><div><button class="person-name" data-action="detail" data-id="${c.id}">${esc(c.remark)}</button><div class="person-meta">${esc(c.wxid)}</div></div></div></td><td>${roleTag(c.role)}${c.manual ? '<div class="person-meta">人工确认</div>' : ""}</td><td><div class="source-names">${c.sources.map((s) => `<span>${esc(s)}</span>`).join("")}</div></td><td><button class="role-edit" data-action="edit-role" data-id="${c.id}">修改身份 ${icon("edit")}</button></td></tr>`).join("")}</tbody></table>`;
    return (
      meta +
      selection +
      (rows.length ? table : empty) +
      `<div class="list-bottom"><div class="pagination"><button class="icon-button" aria-label="上一页" data-action="page" data-delta="-1" ${state.page === 1 ? "disabled" : ""}>${icon("back")}</button><span>第 ${state.page} / ${pages} 页</span><button class="icon-button" aria-label="下一页" data-action="page" data-delta="1" ${state.page === pages ? "disabled" : ""}>${icon("arrow")}</button></div></div>`
    );
  }
  function updateSelectionUI() {
    const slot = $(".selection-slot");
    if (!slot) return;
    const count = state.selection.size,
      focusWithin = slot.contains(document.activeElement);
    if (count)
      slot.querySelector("strong").textContent = `已选 ${count} 位联系人`;
    slot.dataset.active = String(!!count);
    slot.setAttribute("aria-hidden", String(!count));
    slot.inert = !count;
    const rows = filtered().slice((state.page - 1) * 20, state.page * 20);
    const selected = rows.filter((c) => state.selection.has(c.id)).length;
    const pageCheckbox = $("#select-page");
    if (pageCheckbox) {
      pageCheckbox.checked = rows.length > 0 && selected === rows.length;
      pageCheckbox.indeterminate = selected > 0 && selected < rows.length;
    }
    $$("[data-contact-select]").forEach((input) => {
      input.checked = state.selection.has(input.dataset.contactSelect);
      input.closest("tr").classList.toggle("is-selected", input.checked);
    });
    if (!count && focusWithin) $("[data-contact-select]")?.focus();
  }
  function transitionResults(region, html) {
    if (!region) return;
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const previousHeight = region.getBoundingClientRect().height;
    region.getAnimations().forEach((a) => a.cancel());
    const next = document.createElement("div");
    next.innerHTML = html;
    const oldTable = region.querySelector("table"),
      newTable = next.querySelector("table");
    if (oldTable && newTable && oldTable.className === newTable.className) {
      const key = (row) =>
        row.querySelector("[data-action=detail]")?.dataset.id;
      const existing = new Map(
        [...oldTable.tBodies[0].rows].map((row) => [
          key(row),
          { row, y: row.getBoundingClientRect().top },
        ]),
      );
      const incoming = [...newTable.tBodies[0].rows].map((row) => ({
        key: key(row),
        fresh: row,
      }));
      oldTable.tBodies[0].replaceChildren(
        ...incoming.map((item) => {
          const prior = existing.get(item.key)?.row;
          if (!prior) return item.fresh;
          [...item.fresh.cells].forEach((cell, i) => {
            if (prior.cells[i]?.innerHTML !== cell.innerHTML)
              prior.cells[i].innerHTML = cell.innerHTML;
          });
          return prior;
        }),
      );
      for (const cls of ["list-meta", "list-bottom"]) {
        const old = region.querySelector("." + cls),
          replacement = next.querySelector("." + cls);
        if (old && replacement) old.innerHTML = replacement.innerHTML;
      }
      if (!reduced)
        incoming.forEach((item) => {
          const prior = existing.get(item.key),
            row = prior?.row || item.fresh;
          const y = row.getBoundingClientRect().top;
          row.getAnimations().forEach((a) => a.cancel());
          if (prior && Math.abs(prior.y - y) > 1)
            row.animate(
              [
                { transform: `translateY(${prior.y - y}px)` },
                { transform: "none" },
              ],
              { duration: 240, easing: "cubic-bezier(.22,1,.36,1)" },
            );
          else if (!prior)
            row.animate(
              [
                { opacity: 1, transform: "translateY(4px)" },
                { opacity: 1, transform: "none" },
              ],
              { duration: 200, easing: "cubic-bezier(.22,1,.36,1)" },
            );
        });
    } else {
      region.innerHTML = html;
    }
    if (reduced) {
      region.style.overflow = "";
      return;
    }
    const nextHeight = region.getBoundingClientRect().height;
    if (Math.abs(previousHeight - nextHeight) < 1) return;
    region.style.overflow = "clip";
    const animation = region.animate(
      [{ height: previousHeight + "px" }, { height: nextHeight + "px" }],
      { duration: 240, easing: "cubic-bezier(.22,1,.36,1)" },
    );
    region._resultAnimation = animation;
    const settle = () => {
      if (region._resultAnimation === animation) {
        region.style.overflow = "";
        delete region._resultAnimation;
      }
    };
    animation.onfinish = settle;
    animation.oncancel = settle;
  }
  function bindListInput() {
    const input = $("#list-search");
    if (input)
      input.addEventListener("input", () => {
        state.query = input.value;
        $(".search-clear").hidden = !input.value;
        state.page = 1;
        transitionResults($("#list-region"), renderList());
        updateSelectionUI();
      });
  }
  function renderTimeControl() {
    const [h, m] = state.time.split(":");
    const column = (unit, count, selected, label) =>
      `<div class="time-column"><span class="time-column-label">${label}</span><div class="time-options" role="listbox" aria-label="${label}">${Array.from(
        { length: count },
        (_, i) => String(i).padStart(2, "0"),
      )
        .map(
          (value) =>
            `<button type="button" role="option" aria-selected="${value === selected}" aria-label="${value} ${unit === "hour" ? "时" : "分"}" tabindex="${value === selected ? 0 : -1}" data-action="time-option" data-unit="${unit}" data-value="${value}">${value}</button>`,
        )
        .join("")}</div></div>`;
    return `<div class="time-control"><div class="time-picker-field"><label class="sr-only" for="daily-time">每日整理时间（北京时间）</label><input class="time-input" id="daily-time" type="text" inputmode="numeric" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" maxlength="5" aria-describedby="daily-time-error" placeholder="08:30" value="${state.time}" ${state.daily ? "" : "disabled"}><button class="time-trigger icon-button" type="button" id="time-trigger" popovertarget="time-popover" aria-label="选择每日整理时间" aria-haspopup="dialog" aria-expanded="false" aria-controls="time-popover" ${state.daily ? "" : "disabled"}>${icon("clock")}</button></div><p id="daily-time-error" class="field-error" role="alert"></p><div id="time-popover" class="time-popover" popover role="dialog" aria-label="选择每日整理时间"><header class="time-picker-head"><div><strong>每天开始时间</strong><span>北京时间</span></div><button class="icon-button" type="button" data-action="time-cancel" aria-label="关闭时间选择">${icon("close")}</button></header><div class="time-columns">${column("hour", 24, h, "小时")}<span class="time-colon" aria-hidden="true">:</span>${column("minute", 60, m, "分钟")}</div><footer class="time-picker-footer"><button class="btn" data-action="time-cancel">取消</button><button class="btn btn--primary" data-action="time-apply">应用</button></footer></div></div>`;
  }
  function updateTimeDraft(button) {
    if (!state.timeDraft) return;
    state.timeDraft[button.dataset.unit] = button.dataset.value;
    const list = button.closest(".time-options");
    $$("[role=option]", list).forEach((option) => {
      const selected = option === button;
      option.setAttribute("aria-selected", String(selected));
      option.tabIndex = selected ? 0 : -1;
    });
    list.scrollTo({
      top: Math.max(
        0,
        button.offsetTop - (list.clientHeight - button.offsetHeight) / 2,
      ),
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  }
  function closeTimePicker() {
    const picker = $("#time-popover");
    if (picker?.matches(":popover-open")) picker.hidePopover();
    $("#time-trigger")?.focus();
  }
  function showTimePicker(picker) {
    const input = $("#daily-time");
    const current = /^([01]\d|2[0-3]):[0-5]\d$/.test(input.value)
      ? input.value
      : state.time;
    const [hour, minute] = current.split(":");
    state.timeDraft = { hour, minute };
    $$("[data-action=time-option]", picker).forEach((option) => {
      const selected =
        option.dataset.value === state.timeDraft[option.dataset.unit];
      option.setAttribute("aria-selected", String(selected));
      option.tabIndex = selected ? 0 : -1;
    });
    const rect = $(".time-picker-field").getBoundingClientRect(),
      height = picker.getBoundingClientRect().height;
    picker.style.left =
      Math.max(12, Math.min(innerWidth - 292, rect.right - 280)) + "px";
    picker.style.top =
      Math.max(
        12,
        rect.bottom + 8 + height < innerHeight - 12
          ? rect.bottom + 8
          : rect.top - height - 8,
      ) + "px";
    $$(".time-options", picker).forEach((list) => {
      const option = $("[aria-selected=true]", list);
      list.scrollTop = Math.max(
        0,
        option.offsetTop - (list.clientHeight - option.offsetHeight) / 2,
      );
    });
    $(".time-options [aria-selected=true]", picker)?.focus({
      preventScroll: true,
    });
  }
  function renderSettings() {
    return `<header class="page-head"><div><h1>设置</h1><p>连接、身份与整理节奏，保持简单。</p></div></header><div class="settings-grid"><section class="settings-card"><div class="settings-card-head">${icon("shield")}<div><h2>本机数据与模型</h2><p>连接状态如实展示，原始资料始终可查。</p></div></div><div class="settings-body"><div class="setting-row"><div><strong>工作微信 / wx-cli</strong><p>当前为交互原型，尚未连接真实账号和消息源。</p></div><button class="btn" data-action="connection">连接说明</button></div><div class="setting-row"><div><strong>DeepSeek Pro</strong><p>实际 API 版本与能力将在接入时核验；此原型不会调用模型。</p></div>${tag("待接入", "neutral")}</div><div class="setting-row"><div><strong>图片与文件</strong><p>区分原文件、缩略图、未获取和未解析；消息正文不因媒体缺失而丢弃。</p></div><button class="text-button" data-action="attachment" data-kind="file">查看示例 ${icon("arrow")}</button></div></div><div class="settings-note">模型只整理身份为<strong>商家</strong>的客户；其他参与人的相关发言保留为上下文。</div></section>
      <section class="settings-card"><div class="settings-card-head">${icon("clock")}<div><h2>每日整理</h2><p>初次整理完整历史；之后按天更新有新消息的商家。</p></div></div><div class="settings-body"><div class="setting-row"><div><strong id="daily-label">每日自动整理</strong><p>关闭后不再自动发起新任务，仍可手动开始。</p></div><div class="switch-hit"><button class="switch" role="switch" aria-labelledby="daily-label" aria-checked="${state.daily}" data-action="daily-toggle"></button></div></div><div class="setting-row"><div><strong>每天开始时间</strong><p>当天错过计划时，启动应用后补跑一次。</p></div>${renderTimeControl()}</div></div><div class="settings-note">整理控制为演示交互；生产版调度尚未接入。只显示用量记录，不设置每日 Token 上限。</div></section>
      <section class="settings-card"><div class="settings-card-head">${icon("theme")}<div><h2>外观与原型</h2><p>使用系统字体，支持浅色、深色和减少动态效果。</p></div></div><div class="settings-body"><div class="setting-row appearance"><div><strong>外观</strong><p>跟随设备，也可以单独选择。</p></div><div class="segmented" aria-label="外观选择">${[
        ["system", "跟随系统"],
        ["light", "浅色"],
        ["dark", "深色"],
      ]
        .map(
          ([value, label]) =>
            `<button aria-pressed="${state.theme === value}" data-action="theme" data-value="${value}">${label}</button>`,
        )
        .join(
          "",
        )}</div></div><div class="setting-row"><div><strong>示例数据</strong><p>身份调整、单号和字段纠正只保存在当前浏览器。</p></div><button class="btn" data-action="reset-demo">重置示例</button></div></div></section></div>`;
  }
  function profileFor(c) {
    if (c.id === "c01") return structuredClone(window.DEMO.profile);
    return {
      goods: [
        ["主营类目", c.goods ? c.goods.split(" · ")[0] : "尚未整理", []],
        ["具体货品", c.goods?.split(" · ")[1] || "尚未整理", []],
      ],
      logistics: [["路线", c.route || "尚未整理", []]],
      shipments: [],
    };
  }
  function messagesFor(c) {
    if (c.id === "c01") return window.DEMO.messages;
    return [];
  }
  function openDetail(id) {
    state.detail = id;
    state.detailTab = "overview";
    state.timelineQuery = "";
    renderDetail();
    $("#detail-dialog").showModal();
    moveIndicator(null);
  }
  function renderDetail() {
    const c = contact(state.detail);
    if (!c) return;
    const p = profileFor(c);
    const previousTab = $("#detail-dialog [role=tab][aria-selected=true]");
    const previous = previousTab
      ? { x: previousTab.offsetLeft, w: previousTab.offsetWidth }
      : null;
    $("#detail-dialog").innerHTML =
      `<header class="detail-header"><div class="header-person"><span class="avatar blue header-avatar" aria-hidden="true">${esc(c.name.slice(0, 1))}</span><div class="detail-primary"><div class="detail-title-row"><h2 id="detail-title">${esc(c.name)}</h2><button class="identity-chip current-identity" data-action="edit-role" data-id="${c.id}" aria-label="修改身份" title="修改身份">${roleTag(c.role)}${icon("arrow")}</button><button class="icon-button name-copy" aria-label="复制微信名称" title="复制微信名称" data-action="copy" data-value="${esc(c.name)}">${icon("copy")}</button></div><div class="identity-id" title="微信内部标识">${esc(c.wxid)}</div></div></div><div class="detail-header-actions"><button class="btn btn--small" data-action="sync-customer" data-id="${c.id}">${icon("refresh")}${c.role === "商家" ? "同步此客户" : "同步消息"}</button><button class="icon-button" aria-label="关闭客户档案" data-action="close-detail">${icon("close")}</button></div></header><div class="detail-layout"><div class="detail-content"><div class="detail-tabs" role="tablist" aria-label="客户档案内容">${[
        ["overview", "资料概览"],
        ["shipments", "备货记录"],
        ["timeline", "沟通原文"],
      ]
        .map(
          ([value, label]) =>
            `<button role="tab" id="detail-tab-${value}" aria-controls="detail-panel" aria-selected="${state.detailTab === value}" tabindex="${state.detailTab === value ? 0 : -1}" data-action="detail-tab" data-tab="${value}">${label}</button>`,
        )
        .join(
          "",
        )}</div><section id="detail-panel" role="tabpanel" aria-labelledby="detail-tab-${state.detailTab}" tabindex="0">${c.role !== "商家" ? `<div class="empty">${icon("people")}<h2>${esc(c.role)}不参与客户档案整理</h2><p>关联消息仍作为沟通来源保留。只有身份为商家的联系人会进入分析。</p><button class="btn" data-action="edit-role" data-id="${c.id}">修改身份</button></div>` : state.detailTab === "overview" ? renderOverview(c, p) : state.detailTab === "shipments" ? renderShipments(c, p) : renderTimeline(c)}</section></div></div>`;
    moveIndicator(previous);
  }
  function moveIndicator(previous) {
    $(".detail-tabs .tab-glass")?.remove();
    const selected = $("#detail-dialog [role=tab][aria-selected=true]");
    if (!selected) return;
    const indicator = document.createElement("span");
    indicator.className = "tab-glass";
    indicator.setAttribute("aria-hidden", "true");
    indicator.style.left = selected.offsetLeft + "px";
    indicator.style.width = selected.offsetWidth + "px";
    $(".detail-tabs").prepend(indicator);
    if (previous && !matchMedia("(prefers-reduced-motion: reduce)").matches)
      indicator.animate(
        [
          {
            transform: `translateX(${previous.x - selected.offsetLeft}px) scaleX(${previous.w / selected.offsetWidth})`,
          },
          { transform: "none" },
        ],
        { duration: 320, easing: "cubic-bezier(.22,1,.36,1)" },
      );
  }
  function sectionEntries(c, section) {
    return profileFor(c)[section].map(([label, value, sources], index) => ({
      label,
      value: state.edits[`${c.id}-${section}-${index}`] || value,
      sources,
      key: `${c.id}-${section}-${index}`,
    }));
  }
  function sectionValue(c, section, index) {
    return sectionEntries(c, section)[index]?.value || "尚未明确";
  }
  function renderSupplement(c, section) {
    const text = state.supplements[`${c.id}-${section}`];
    return text
      ? `<div class="dossier-supplement"><span class="supplement-label">人工补充</span><p>${esc(text)}</p></div>`
      : "";
  }
  function sectionActions(c, section, title) {
    const changed = sectionEntries(c, section).some((e) => state.edits[e.key]);
    return `<footer class="dossier-actions"><button class="text-button" data-action="section-evidence" data-section="${section}" aria-label="查看${title}来源">${icon("source")}查看来源</button><button class="text-button" data-action="edit-section" data-section="${section}" aria-label="编辑${title}">${icon("edit")}编辑资料</button>${changed ? '<span class="manual-mark">人工纠正</span>' : ""}</footer>`;
  }
  function renderOverview(c, p) {
    const goods = sectionEntries(c, "goods"),
      logistics = sectionEntries(c, "logistics");
    const row = (label, value, cls = "") =>
      `<div class="dossier-row ${cls}"><dt>${label}</dt><dd>${esc(value)}</dd></div>`;
    const full = c.id === "c01";
    return `<div class="overview-intro"><div class="eyebrow">${(c.tags.length ? c.tags : ["待整理"]).join(" · ")}</div><h3>${esc(c.summary)}</h3></div>
    <article class="dossier-card" aria-labelledby="goods-heading"><header><span class="dossier-symbol">${icon("file")}</span><h3 id="goods-heading">货品概况</h3></header><p class="dossier-headline">${esc(
      goods
        .slice(0, 2)
        .map((e) => e.value)
        .join(" · "),
    )}</p><dl class="dossier-rows">${goods
      .slice(2)
      .map((e) =>
        row(e.label === "特殊属性" ? "货物属性" : "货量情况", e.value),
      )
      .join(
        "",
      )}</dl>${renderSupplement(c, "goods")}${sectionActions(c, "goods", "货品概况")}</article>
    <article class="dossier-card" aria-labelledby="logistics-heading"><header><span class="dossier-symbol">${icon("workspace")}</span><h3 id="logistics-heading">物流需求</h3></header><p class="dossier-headline">${esc(full ? `${logistics[0].value} → ${logistics[1].value} · ${logistics[2].value.split(/[；;]/)[0]}` : logistics[0]?.value || "尚未整理")}</p><dl class="dossier-rows">${full ? row("运输诉求", logistics[3].value) + row("服务要求", logistics[4].value + "；" + logistics[7].value) + row("时效要求", logistics[5].value) + row("价格与顾虑", logistics[6].value + "；" + logistics[8].value) : ""}${row("尚未明确", full ? "仓库名称、最晚到仓日、新批实际重量" : "完整沟通资料尚未整理", "missing-row")}</dl>${renderSupplement(c, "logistics")}${sectionActions(c, "logistics", "物流需求")}</article>
    ${full ? `<div class="compact-history"><div><span class="muted">最近沟通</span><time>11月9日 14:12</time></div><button class="text-button" data-action="detail-tab" data-tab="shipments">2 条备货记录 ${icon("arrow")}</button></div>` : ""}`;
  }
  function openSectionEvidence(section) {
    const c = contact(state.detail);
    const entries = sectionEntries(c, section);
    overlay(
      section === "goods" ? "货品来源" : "物流来源",
      `<div class="evidence-sections">${entries
        .map(
          (e, i) =>
            `<details class="evidence-group" ${i === 0 ? "open" : ""}><summary><span>${esc(e.label)}</span><strong>${esc(e.value)}</strong>${icon("arrow")}</summary><div class="evidence-content">${
              e.sources.length
                ? messagesFor(c)
                    .filter((m) => e.sources.includes(m.id))
                    .map(messageHtml)
                    .join("")
                : '<p class="muted">暂无关联原文</p>'
            }</div></details>`,
        )
        .join("")}</div>`,
    );
  }
  function editorFields(entries, section) {
    const field = (index, wide = false) => {
      const e = entries[index];
      if (!e) return "";
      const single = section === "goods" ? index < 2 : index < 3;
      return `<label class="form-field editor-field ${wide ? "editor-field-wide" : ""}"><span>${esc(e.label)}</span>${single ? `<input type="text" name="${e.key}" value="${esc(e.value)}" required maxlength="600" autocomplete="off">` : `<textarea name="${e.key}" required maxlength="600" rows="1">${esc(e.value)}</textarea>`}</label>`;
    };
    const group = (title, indexes, wideIndex = -1) =>
      `<fieldset class="editor-group"><legend>${title}</legend><div class="editor-grid">${indexes
        .filter((i) => entries[i])
        .map((i) => field(i, i === wideIndex))
        .join("")}</div></fieldset>`;
    if (section === "goods")
      return (
        group("货品信息", [0, 1]) +
        (entries.length > 2 ? group("属性与货量", [2, 3]) : "")
      );
    if (entries.length < 3)
      return group(
        "路线信息",
        entries.map((_, i) => i),
      );
    return (
      group("路线与目的地", [0, 1, 2], 2) +
      group("运输与服务", [3, 4, 5, 7]) +
      group("费用与关注", [6, 8])
    );
  }
  function openSectionEditor(section) {
    const c = contact(state.detail);
    const entries = sectionEntries(c, section);
    overlay(
      section === "goods" ? "编辑货品资料" : "编辑物流资料",
      `<form id="section-form" class="section-editor" data-section="${section}">${editorFields(entries, section)}<fieldset class="editor-group supplement-editor"><legend>补充资料</legend><label class="form-field editor-field"><span class="sr-only">补充资料</span><textarea name="supplement" maxlength="1500" rows="1" placeholder="填写补充资料">${esc(state.supplements[`${c.id}-${section}`] || "")}</textarea></label></fieldset><p id="section-error" class="field-error" role="alert"></p></form>`,
      `<button class="btn" data-action="close-overlay">取消</button><button class="btn btn--primary" form="section-form" type="submit">保存资料</button>`,
      "editor",
    );
    $("#section-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      const values = entries.map((entry) =>
        String(form.get(entry.key) || "").trim(),
      );
      if (values.some((v) => !v)) {
        $("#section-error").textContent =
          "请填写资料，未确定的内容可标记为尚未明确。";
        return;
      }
      entries.forEach((entry, i) => {
        if (entry.value !== values[i]) state.edits[entry.key] = values[i];
      });
      const note = String(form.get("supplement") || "").trim();
      const noteKey = `${c.id}-${section}`;
      if (note) state.supplements[noteKey] = note;
      else delete state.supplements[noteKey];
      persist();
      $("#overlay-dialog").close();
      renderDetail();
      $(`[data-action="edit-section"][data-section="${section}"]`).focus();
      toast("资料已保存");
    });
  }
  function renderShipments(c, p) {
    return `${
      p.shipments.length
        ? p.shipments
            .map((s) => {
              const numbers = [
                ...new Set([
                  ...s.numbers,
                  ...(state.numbers[`${c.id}-${s.id}`] || []),
                ]),
              ];
              return `<article class="shipment"><div class="shipment-head"><div><h3>${s.title}</h3><p class="shipment-time">${s.date}</p></div>${tag(s.stage, s.stage === "已走货" ? "positive" : "")}</div><dl class="shipment-fields"><div><dt>货品 / 货量</dt><dd>${s.goods}</dd></div><div><dt>起运 / 目的</dt><dd>${s.route}</dd></div><div><dt>运输要求</dt><dd>${s.mode}</dd></div><div><dt>关联单号</dt><dd>${numbers.length ? numbers.map((n) => `<span class="number-chip">${esc(n)}</span>`).join("") : '<span class="muted">尚未录入</span>'}</dd></div></dl><div class="shipment-actions"><button class="text-button" data-action="evidence" data-ids="${s.sources.join(",")}">${icon("source")}查看来源</button><button class="text-button" data-action="add-number" data-shipment="${s.id}">${icon("plus")}录入单号</button></div></article>`;
            })
            .join("")
        : `<div class="empty">${icon("file")}<h2>尚未配置备货示例</h2><p>此联系人用于列表展示。陈屿档案可体验新旧批次与单号录入。</p></div>`
    }`;
  }
  function messageHtml(m) {
    return `<article class="message ${m.speaker === "我" ? "own" : ""}"><div class="message-meta"><strong>${esc(m.speaker)}</strong>${roleTag(state.contacts.find((c) => c.id === m.contactId)?.role || m.role)}<time>${esc(m.at)} 北京时间</time></div><p>${esc(m.text)}</p><div class="message-location">${esc(m.source)}</div>${(m.attachments || []).map((a) => `<button class="attachment" data-action="attachment" data-kind="${a.type}">${icon(a.type === "image" ? "image" : "file")}<span><strong>${esc(a.name)}</strong><small>${esc(a.state)}</small></span>${icon("arrow", "chev")}</button>`).join("")}</article>`;
  }
  function timelineMessages(c) {
    const q = state.timelineQuery.toLowerCase().trim();
    const ms = messagesFor(c).filter(
      (m) =>
        !q ||
        [m.text, m.speaker, m.source].some((v) => v.toLowerCase().includes(q)),
    );
    let day = "";
    return ms.length
      ? ms
          .map((m) => {
            const d = m.at.slice(0, 10);
            const group =
              d !== day ? `<div class="timeline-group">${d}</div>` : "";
            day = d;
            return group + messageHtml(m);
          })
          .join("")
      : '<div class="empty"><p>没有匹配的沟通原文。</p></div>';
  }
  function renderTimeline(c) {
    return `<label class="search-field timeline-search"><span class="search-caption">查找沟通原文</span>${icon("search")}<input id="timeline-search" type="search" value="${esc(state.timelineQuery)}" placeholder="查找原文、参与人或来源" aria-label="搜索沟通原文"><button type="button" class="search-clear" data-action="clear-search" data-target="timeline-search" aria-label="清空原文搜索" ${state.timelineQuery ? "" : "hidden"}>${icon("close")}</button></label><div id="timeline-messages">${timelineMessages(c)}</div>`;
  }
  function overlay(title, body, footer = "", kind = "generic") {
    const el = $("#overlay-dialog");
    if (el.open) el.close();
    el.dataset.kind = kind;
    el.innerHTML = `<header class="overlay-header"><h2 id="overlay-title">${title}</h2><button class="icon-button" aria-label="关闭${title}" data-action="close-overlay">${icon("close")}</button></header><div class="overlay-body">${body}</div>${footer ? `<div class="overlay-footer">${footer}</div>` : ""}`;
    el.showModal();
    wireFields(el);
  }
  function autoSize(input) {
    if (input.tagName !== "TEXTAREA") return;
    input.style.height = "auto";
    input.style.height =
      Math.min(240, Math.max(48, input.scrollHeight + 2)) + "px";
  }
  function clearFieldError(input) {
    input.removeAttribute("aria-invalid");
    const error = input.closest(".form-field")?.querySelector(".input-error");
    error?.remove();
  }
  function validateField(input) {
    clearFieldError(input);
    let message = "";
    if (input.required && !input.value.trim())
      message =
        "请填写" +
        (input.closest(".form-field")?.querySelector("span")?.textContent ||
          "此项");
    if (!message) return true;
    input.setAttribute("aria-invalid", "true");
    const error = document.createElement("small");
    error.className = "input-error";
    error.textContent = message;
    error.setAttribute("role", "alert");
    input.closest(".form-field")?.append(error);
    return false;
  }
  function wireFields(root) {
    const form = root.querySelector("form");
    if (!form) return;
    form.noValidate = true;
    const fields = $$("textarea,input:not([type=radio])", form);
    fields.forEach(autoSize);
    const dirty = ["section-form", "role-form"].includes(form.id);
    const initial = JSON.stringify([...new FormData(form)]);
    const submit = root.querySelector("[type=submit]");
    const sync = () => {
      if (submit && dirty)
        submit.disabled = JSON.stringify([...new FormData(form)]) === initial;
    };
    sync();
    form.addEventListener("input", (e) => {
      if (e.target.matches("input,textarea")) {
        clearFieldError(e.target);
        autoSize(e.target);
      }
      sync();
    });
    form.addEventListener("change", sync);
    form.addEventListener("focusout", (e) => {
      if (
        e.target.matches("textarea,input:not([type=radio])") &&
        e.target.required
      )
        validateField(e.target);
    });
    form.addEventListener(
      "submit",
      (e) => {
        const valid = fields.map(validateField);
        if (valid.includes(false)) {
          e.preventDefault();
          e.stopImmediatePropagation();
          fields[valid.indexOf(false)].focus();
        }
      },
      true,
    );
  }
  function openRole(ids) {
    const same = ids.every((id) => contact(id).role === contact(ids[0]).role);
    const current = same ? contact(ids[0]).role : "";
    overlay(
      ids.length === 1 ? "修改联系人身份" : "批量设置身份",
      `<p class="overlay-lead">${ids.length === 1 ? esc(contact(ids[0]).remark) : `已选择 ${ids.length} 位联系人`}。只对商家整理客户档案；人工选择优先于模型判断。</p><form id="role-form"><fieldset class="role-options"><legend>联系人身份</legend>${[
        ["商家", "需要整理货品、物流需求和备货记录"],
        ["服务商", "保留沟通来源，不作客户分析"],
        ["平台", "保留平台对接信息，不作客户分析"],
        ["待识别", "尚未确认身份，暂不进入客户分析"],
      ]
        .map(
          ([value, desc]) =>
            `<label class="role-option ${value === "待识别" ? "unresolved" : ""}"><input type="radio" name="role" value="${value}" ${current === value ? "checked" : ""} required><div><strong>${value}</strong><span>${desc}</span></div></label>`,
        )
        .join(
          "",
        )}</fieldset><p class="privacy-note">修改身份不删除聊天记录。改为非商家后会从商家列表移出。</p></form>`,
      `<button class="btn" data-action="close-overlay">取消</button><button class="btn btn--primary" type="submit" form="role-form">保存身份</button>`,
      "role",
    );
    $("#role-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const role = new FormData(e.target).get("role");
      if (!role) return;
      setIdentity(ids, role);
      $("#overlay-dialog").close();
      toast(`已将 ${ids.length} 位联系人设为${role}`);
    });
  }
  // Shared identity operation for individual and batch editing.
  function setIdentity(ids, role) {
    ids.forEach((id) => {
      const c = contact(id);
      if (!c) return;
      c.role = role;
      c.manual = true;
      state.roles[id] = role;
      if (role === "商家" && !c.tags.length) {
        c.tags = ["待整理"];
        c.summary = "身份已确认，等待整理完整的相关聊天资料。";
      }
    });
    const r = state.run;
    if (["running", "stopped"].includes(r.status)) {
      const previous = r.queue[r.done];
      r.queue = [
        ...r.queue.slice(0, r.done),
        ...r.queue.slice(r.done).filter((id) => contact(id)?.role === "商家"),
      ];
      if (r.done >= r.queue.length) {
        clearTimeout(runTimer);
        r.status = "completed";
        r.finished = humanTime();
      } else if (previous !== r.queue[r.done]) {
        r.stage = 0;
        if (r.status === "running") scheduleStep();
      }
    }
    state.selection.clear();
    persist();
    render();
    if ($("#detail-dialog").open) {
      renderDetail();
      $("#detail-dialog [role=tab][aria-selected=true]").focus();
    }
  }
  function openEvidence(ids) {
    const ms = messagesFor(contact(state.detail)).filter((m) =>
      ids.includes(m.id),
    );
    overlay("来源原文", `${ms.map(messageHtml).join("")}`);
  }
  function openNumber(shipmentId) {
    const c = contact(state.detail);
    const s = profileFor(c).shipments.find((s) => s.id === shipmentId);
    overlay(
      "录入单号",
      `<p class="overlay-lead">${esc(s.title)} · ${esc(s.stage)}。支持录入多个订单号、运单号或柜号，每行一个。</p><form id="number-form"><label class="form-field"><span>关联单号</span><textarea name="numbers" rows="1" placeholder="例如：DEMO-CY-NEW-01" aria-describedby="number-hint number-error" autofocus></textarea><small id="number-hint">仅补充此批记录，不会自动标为已走货。</small></label><p id="number-error" class="field-error" role="alert"></p></form>`,
      `<button class="btn" data-action="close-overlay">取消</button><button class="btn btn--primary" type="submit" form="number-form">保存单号</button>`,
    );
    $("#number-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const values = String(new FormData(e.target).get("numbers"))
        .split(/[\n,，]/)
        .map((v) => v.trim())
        .filter(Boolean);
      if (!values.length) {
        $("#number-error").textContent = "请至少填写一个单号。";
        return;
      }
      if (values.some((v) => v.length > 120)) {
        $("#number-error").textContent = "单个单号请控制在 120 个字符以内。";
        return;
      }
      const k = `${c.id}-${s.id}`;
      state.numbers[k] = [...new Set([...(state.numbers[k] || []), ...values])];
      persist();
      $("#overlay-dialog").close();
      renderDetail();
      $("#detail-tab-shipments").focus();
      toast("单号已保存，批次进度保持不变");
    });
  }
  function openAttachment(kind) {
    if (kind === "image")
      overlay(
        "图片预览",
        `<img class="preview-image" src="assets/product.svg" alt="演示用的三只半透明塑料收纳盒，带蓝色盖子"><p class="privacy-note">本地绘制的示例附件，不是真实客户图片。</p>`,
      );
    else
      overlay(
        "备货清单预览",
        `<p class="overlay-lead">11月备货清单.csv · 本地演示文件</p><table class="file-table"><caption class="sr-only">示例备货清单</caption><thead><tr><th>货品</th><th>预估体积</th><th>重量</th></tr></thead><tbody><tr><td>塑料收纳盒</td><td>约 12 方</td><td>待称重</td></tr></tbody></table><p class="privacy-note">文件提及的预估货量不能替代实测装箱数据。</p>`,
        `<a class="btn" href="assets/11月备货清单.csv" download>下载示例 CSV</a>`,
      );
  }
  function renderRunBody() {
    const r = state.run,
      remaining = runRemaining();
    const pct = r.queue.length
      ? Math.round(
          ((r.done + (r.status === "running" ? r.stage / 3 : 0)) /
            r.queue.length) *
            100,
        )
      : 0;
    const list = r.queue
      .map((id, i) => {
        const c = contact(id);
        const done = i < r.done,
          active = i === r.done && r.status === "running";
        return `<li><span class="avatar ${active ? "blue" : ""}">${esc(c.name.slice(-2))}</span><div><strong>${esc(c.name)}</strong><p>${done ? "档案与来源已保存" : c.role !== "商家" ? "身份已调整，将跳过" : active ? runStages[r.stage] : "等待整理"}</p></div><span class="queue-status ${done ? "done" : active ? "running" : ""}">${done ? "已完成" : active ? "进行中" : r.status === "stopped" ? "已停止" : "待开始"}</span></li>`;
      })
      .join("");
    return `<p class="overlay-lead">这是整理控制的交互演示，不会调用模型或发送聊天记录。</p><div class="progress-heading"><strong>${runLabels[r.status]}</strong><span>${r.done} / ${r.queue.length} 位</span></div><div class="progress-track"><span style="width:${pct}%"></span></div><p class="progress-note">${r.status === "idle" ? "点击立即整理，体验按商家合并来源后生成资料。" : r.status === "completed" ? "所有本次任务已结束，不再显示暂停或继续按钮。" : r.status === "stopped" ? `剩余 ${remaining} 位可继续；已完成的资料无需重跑。` : "先整理完整历史，再归纳客户档案；非商家不会进入队列。"}</p>${list ? `<ul class="queue-list">${list}</ul>` : ""}<div class="run-explanation">停止本次会阻止后续请求；正式接入后，已经发出的远端请求可能仍计费。已完成资料保留，不把未完成结果发布为完整档案。</div>`;
  }
  function runFooter() {
    const [cmd, label, ico] = runAction();
    return `<button class="btn" data-action="close-overlay">关闭</button><button class="btn btn--primary" data-action="run-command" data-command="${cmd}">${icon(ico)}${label}</button>`;
  }
  function openSync(target = null) {
    if (state.run.status === "running") {
      openRun();
      return;
    }
    const c = target ? contact(target) : null;
    overlay(
      c ? `同步${esc(c.name)}的消息` : "同步微信数据",
      `<div class="sync-status">${tag("微信未连接", "warning")}<span>${c ? esc(c.name) : "全部已接入会话"}</span></div><ol class="sync-steps"><li><span>1</span><div><strong>读取最新聊天</strong><p>${c ? "此联系人的私信与相关群聊" : "私信与群聊"}</p></div></li><li><span>2</span><div><strong>检查新增记录</strong><p>按消息标识去重</p></div></li><li><span>3</span><div><strong>${c && c.role !== "商家" ? "保存原始记录" : "更新商家档案"}</strong><p>${c && c.role !== "商家" ? "不进行客户分析" : "有新增时更新，没有新增则保留现有档案"}</p></div></li></ol><p class="sync-boundary">当前为交互原型，尚未连接 wx-cli。演示整理只使用已有示例消息。</p>`,
      `<button class="btn" data-action="sync-settings">前往设置</button>${!c || c.role === "商家" ? `<button class="btn btn--primary" data-action="demo-sync" data-id="${c?.id || ""}">演示整理</button>` : ""}`,
      "sync",
    );
  }
  function openRun() {
    overlay("整理进度", renderRunBody(), runFooter(), "run");
  }
  function updateRunUI() {
    persist();
    if (location.hash !== "#settings") {
      const strip = $("#run-strip");
      if (strip) strip.outerHTML = renderRunStrip();
      const action = $('.head-actions [data-action="run-command"]');
      const [cmd, label, ico] = runAction();
      if (action) {
        action.dataset.command = cmd;
        action.innerHTML = icon(ico) + label;
      }
      const region = $("#list-region");
      if (region) {
        transitionResults(region, renderList());
        updateSelectionUI();
      }
    }
    if (
      $("#overlay-dialog").open &&
      $("#overlay-dialog").dataset.kind === "run"
    ) {
      $("#overlay-dialog .overlay-body").innerHTML = renderRunBody();
      const footer = $("#overlay-dialog .overlay-footer");
      const action = $('[data-action="run-command"]', footer);
      const [cmd, label, ico] = runAction();
      if (action) {
        action.dataset.command = cmd;
        action.innerHTML = icon(ico) + label;
      }
    }
  }
  // One state machine shared by the header and progress dialog. No idle pause/resume.
  function runCommand(command, target = null) {
    if (command === "sync") {
      openSync();
      return;
    }
    const r = state.run;
    if (command === "stop" && r.status === "running") {
      clearTimeout(runTimer);
      r.status = "stopped";
      updateRunUI();
      toast("本次整理已停止，已完成资料保留");
      return;
    }
    if (command === "resume" && r.status === "stopped" && runRemaining()) {
      r.status = "running";
      r.stage = 0;
      updateRunUI();
      scheduleStep();
      return;
    }
    if (command === "start" && r.status !== "running") {
      const candidates = target
        ? merchants().filter((c) => c.id === target)
        : merchants().filter((c) => !c.complete || c.fresh);
      if (!candidates.length) {
        toast("示例中暂无待整理资料");
        return;
      }
      state.run = {
        status: "running",
        queue: candidates.map((c) => c.id),
        done: 0,
        stage: 0,
        target,
      };
      updateRunUI();
      scheduleStep();
      return;
    }
  }
  function scheduleStep() {
    clearTimeout(runTimer);
    runTimer = setTimeout(() => {
      const r = state.run;
      if (r.status !== "running") return;
      const c = contact(r.queue[r.done]);
      if (c?.role !== "商家") {
        r.done++;
        r.stage = 0;
      } else if (r.stage < 2) {
        r.stage++;
      } else {
        c.complete = true;
        c.fresh = false;
        c.updated = `今天 ${humanTime()}`;
        if (c.id === "c05")
          c.summary = "示例整理已完成；真实客户资料将在接入后生成。";
        r.done++;
        r.stage = 0;
      }
      if (r.done >= r.queue.length) {
        r.status = "completed";
        r.finished = humanTime();
        updateRunUI();
        toast("示例整理已完成");
        return;
      }
      updateRunUI();
      scheduleStep();
    }, 1500);
  }
  async function copy(value) {
    try {
      await navigator.clipboard.writeText(value);
      toast("微信名称已复制");
    } catch {
      overlay(
        "复制微信名称",
        `<p class="overlay-lead">当前浏览器不支持自动复制，可以选中下方内容复制。</p><label class="form-field"><span>微信名称</span><input value="${esc(value)}" readonly></label>`,
      );
    }
  }
  function toggleEvidence(details) {
    const opening = !(details._nextOpen ?? details.open),
      summary = details.querySelector("summary"),
      content = details.querySelector(".evidence-content");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      details.open = opening;
      summary.setAttribute("aria-expanded", String(opening));
      return;
    }
    const from = details.getBoundingClientRect().height,
      opacity = getComputedStyle(content).opacity;
    details._accordion?.cancel();
    details._contentAnimation?.cancel();
    details._nextOpen = opening;
    details.open = true;
    summary.setAttribute("aria-expanded", String(opening));
    const target = opening
      ? details.getBoundingClientRect().height
      : summary.getBoundingClientRect().height;
    details.style.overflow = "hidden";
    const animation = details.animate(
      [{ height: from + "px" }, { height: target + "px" }],
      { duration: 260, easing: "cubic-bezier(.22,1,.36,1)" },
    );
    details._accordion = animation;
    details._contentAnimation = content.animate(
      [
        {
          opacity: opening ? 0 : opacity,
          transform: opening ? "translateY(-4px)" : "none",
        },
        {
          opacity: opening ? 1 : 0,
          transform: opening ? "none" : "translateY(-4px)",
        },
      ],
      {
        duration: opening ? 220 : 160,
        fill: "forwards",
        easing: "cubic-bezier(.22,1,.36,1)",
      },
    );
    animation.onfinish = () => {
      if (details._accordion !== animation) return;
      details.open = opening;
      details.style.overflow = "";
      details._contentAnimation?.cancel();
      delete details._accordion;
      delete details._nextOpen;
    };
  }
  document.addEventListener("click", (e) => {
    const summary = e.target.closest(".evidence-group>summary");
    if (!summary) return;
    e.preventDefault();
    toggleEvidence(summary.parentElement);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action]");
    if (!b || b.disabled) return;
    const action = b.dataset.action;
    if (action === "workspace-tab") {
      if (state.tab === b.dataset.tab) return;
      const previous = {
        x: b.parentElement.querySelector("[aria-selected=true]").offsetLeft,
        w: b.parentElement.querySelector("[aria-selected=true]").offsetWidth,
      };
      const direction = b.dataset.tab === "contacts" ? 1 : -1;
      state.tab = b.dataset.tab;
      state.query = "";
      state.filter = "全部";
      state.page = 1;
      state.selection.clear();
      render();
      placeWorkspaceIndicator(previous);
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches)
        $("#workspace-panel .list-surface").animate(
          [
            { opacity: 0, transform: `translateX(${direction * 12}px)` },
            { opacity: 1, transform: "none" },
          ],
          { duration: 280, easing: "cubic-bezier(.22,1,.36,1)" },
        );
      $(`#tab-${state.tab}`).focus();
    }
    if (action === "filter") {
      if (state.filter === b.dataset.filter) {
        if ($("#filter-menu")?.matches(":popover-open")) {
          $("#filter-menu").hidePopover();
          $("#filter-trigger").focus();
        }
        return;
      }
      const group = b.closest(".filter-group"),
        pill = group?.querySelector(".role-filter-indicator");
      const previous = pill
        ? {
            x:
              pill.getBoundingClientRect().left -
              group.getBoundingClientRect().left,
            w: pill.getBoundingClientRect().width,
          }
        : null;
      state.filter = b.dataset.filter;
      state.page = 1;
      if (group) {
        group
          .querySelectorAll(".filter-button")
          .forEach((button) =>
            button.setAttribute(
              "aria-pressed",
              String(button.dataset.filter === state.filter),
            ),
          );
        placeRoleFilterIndicator(previous);
      } else {
        if ($("#filter-menu")?.matches(":popover-open"))
          $("#filter-menu").hidePopover();
        $(".filter-select").outerHTML = renderFilters();
      }
      transitionResults($("#list-region"), renderList());
      updateSelectionUI();
      ($("#filter-trigger") || $(".filter-button[aria-pressed=true]")).focus();
    }
    if (action === "page") {
      state.page += Number(b.dataset.delta);
      transitionResults($("#list-region"), renderList());
      updateSelectionUI();
      $(".list-surface").scrollIntoView({
        block: "start",
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
    }
    if (action === "reset-filter") {
      state.query = "";
      state.filter = "全部";
      state.page = 1;
      render();
      $("#list-search").focus();
    }
    if (action === "clear-search") {
      const input = $(`#${b.dataset.target}`);
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    }
    if (action === "detail") openDetail(b.dataset.id);
    if (action === "close-detail") closeModal($("#detail-dialog"));
    if (action === "close-overlay") closeModal($("#overlay-dialog"));
    if (action === "detail-tab") {
      state.detailTab = b.dataset.tab;
      renderDetail();
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches)
        $("#detail-panel").animate(
          [
            { opacity: 0, transform: "translateY(8px)" },
            { opacity: 1, transform: "none" },
          ],
          { duration: 260, easing: "cubic-bezier(.22,1,.36,1)" },
        );
      $(`#detail-tab-${state.detailTab}`).focus();
    }
    if (action === "edit-role") openRole([b.dataset.id]);
    if (action === "batch-role" && state.selection.size)
      openRole([...state.selection]);
    if (action === "clear-selection") {
      state.selection.clear();
      updateSelectionUI();
    }
    if (action === "evidence") openEvidence(b.dataset.ids.split(","));
    if (action === "add-number") openNumber(b.dataset.shipment);
    if (action === "edit-section") openSectionEditor(b.dataset.section);
    if (action === "section-evidence") openSectionEvidence(b.dataset.section);
    if (action === "attachment") openAttachment(b.dataset.kind);
    if (action === "copy") copy(b.dataset.value);
    if (action === "run-command") runCommand(b.dataset.command);
    if (action === "run-detail") openRun();
    if (action === "sync-customer") openSync(b.dataset.id);
    if (action === "demo-sync") {
      runCommand("start", b.dataset.id || null);
      if (state.run.status === "running") openRun();
    }
    if (action === "sync-settings") {
      $("#overlay-dialog").close();
      $("#detail-dialog").close();
      location.hash = "#settings";
    }
    if (action === "time-option") updateTimeDraft(b);
    if (action === "time-cancel") closeTimePicker();
    if (action === "time-apply" && state.timeDraft) {
      const input = $("#daily-time");
      input.value = state.timeDraft.hour + ":" + state.timeDraft.minute;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      closeTimePicker();
    }
    if (action === "daily-toggle") {
      state.daily = !state.daily;
      persist();
      render();
      $('[data-action="daily-toggle"]').focus();
      toast(
        state.daily
          ? "已开启每日整理（原型设置）"
          : "已关闭每日整理（原型设置）",
      );
    }
    if (action === "theme") {
      state.theme = b.dataset.value;
      persist();
      applyTheme();
      render();
      $(`[data-action="theme"][data-value="${state.theme}"]`)?.focus();
    }
    if (action === "theme-toggle") {
      state.theme = isDark() ? "light" : "dark";
      persist();
      applyTheme();
      if (location.hash === "#settings") render();
    }
    if (action === "connection")
      overlay(
        "连接说明",
        `<p class="overlay-lead">当前只是本地交互原型，没有启动后端。这里不会把演示状态显示成「微信已连接」。</p><div class="fact"><p>后续接入顺序：读取 wx-cli 本机账号与会话 → 归一联系人 → 人工确认身份 → 仅整理商家资料。</p></div><p class="privacy-note">DeepSeek Pro 的具体 API 版本在开发接入时确认。本原型不采集 API Key。</p>`,
      );
    if (action === "reset-demo")
      overlay(
        "重置示例数据",
        `<p class="overlay-lead">只清除本原型中保存的身份、单号、纠正内容、外观和整理状态，恢复初始示例。</p>`,
        `<button class="btn" data-action="close-overlay">取消</button><button class="btn btn--primary" data-action="confirm-reset">重置示例</button>`,
      );
    if (action === "confirm-reset") {
      clearTimeout(runTimer);
      try {
        localStorage.removeItem(key);
      } catch {}
      location.reload();
    }
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "select-page") {
      const rows = filtered().slice((state.page - 1) * 20, state.page * 20);
      rows.forEach((c) =>
        e.target.checked
          ? state.selection.add(c.id)
          : state.selection.delete(c.id),
      );
      updateSelectionUI();
      $("#select-page")?.focus();
    }
    if (e.target.dataset.contactSelect) {
      const id = e.target.dataset.contactSelect;
      e.target.checked ? state.selection.add(id) : state.selection.delete(id);
      updateSelectionUI();
      $(`[data-contact-select=${id}]`)?.focus();
    }
    if (e.target.id === "daily-time") {
      const input = e.target,
        match = input.value.match(/^(\d{1,2}):(\d{2})$/),
        error = $("#daily-time-error");
      if (!match || +match[1] > 23 || +match[2] > 59) {
        input.setAttribute("aria-invalid", "true");
        error.textContent = "请输入 00:00–23:59 之间的时间";
        return;
      }
      input.removeAttribute("aria-invalid");
      error.textContent = "";
      state.time = match[1].padStart(2, "0") + ":" + match[2];
      input.value = state.time;
      persist();
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "daily-time") {
      e.target.removeAttribute("aria-invalid");
      $("#daily-time-error").textContent = "";
    }
    if (e.target.id === "timeline-search") {
      state.timelineQuery = e.target.value;
      $('.search-clear[data-target="timeline-search"]').hidden =
        !e.target.value;
      transitionResults(
        $("#timeline-messages"),
        timelineMessages(contact(state.detail)),
      );
    }
  });
  document.addEventListener(
    "toggle",
    (e) => {
      if (e.target.id === "time-popover") {
        const open = e.newState === "open";
        $("#time-trigger")?.setAttribute("aria-expanded", String(open));
        if (open) showTimePicker(e.target);
        return;
      }
      if (e.target.id !== "filter-menu") return;
      const trigger = $("#filter-trigger");
      const open = e.newState === "open";
      trigger?.setAttribute("aria-expanded", String(open));
      if (open) {
        const r = trigger.getBoundingClientRect();
        e.target.style.left =
          Math.max(12, Math.min(innerWidth - 224, r.right - 220)) + "px";
        e.target.style.top = r.bottom + 8 + "px";
        if (!e.target.contains(document.activeElement))
          e.target.querySelector("[aria-selected=true]")?.focus();
      }
    },
    true,
  );
  document.addEventListener("keydown", (e) => {
    const picker = e.target.closest("#time-popover");
    if (!picker) return;
    if (e.key === "Escape") {
      e.preventDefault();
      closeTimePicker();
      return;
    }
    const list = e.target.closest(".time-options");
    if (!list || !["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key))
      return;
    e.preventDefault();
    const options = $$("[role=option]", list);
    let index = options.indexOf(document.activeElement);
    index =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? options.length - 1
          : Math.max(
              0,
              Math.min(
                options.length - 1,
                index + (e.key === "ArrowDown" ? 1 : -1),
              ),
            );
    const target = options[index];
    updateTimeDraft(target);
    target.focus({ preventScroll: true });
  });
  document.addEventListener("keydown", (e) => {
    if (
      e.target.id === "filter-trigger" &&
      ["ArrowDown", "ArrowUp"].includes(e.key)
    ) {
      e.preventDefault();
      $("#filter-menu").showPopover();
      $("#filter-menu [aria-selected=true]").focus();
      return;
    }
    const menu = e.target.closest("#filter-menu");
    if (
      !menu ||
      !["ArrowDown", "ArrowUp", "Home", "End", "Escape"].includes(e.key)
    )
      return;
    e.preventDefault();
    if (e.key === "Escape") {
      menu.hidePopover();
      $("#filter-trigger").focus();
      return;
    }
    const options = $$("[role=option]", menu);
    let i = options.indexOf(document.activeElement);
    i =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? options.length - 1
          : (i + (e.key === "ArrowDown" ? 1 : -1) + options.length) %
            options.length;
    options[i].focus();
  });
  document.addEventListener("keydown", (e) => {
    const tab = e.target.closest('[role="tab"]');
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
      return;
    const tabs = $$('[role="tab"]', tab.parentElement);
    let i = tabs.indexOf(tab);
    i =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? tabs.length - 1
          : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    e.preventDefault();
    tabs[i].click();
  });
  function closeModal(d) {
    if (!d.open || d.dataset.closing) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      d.close();
      return;
    }
    d.dataset.closing = "true";
    d.animate(
      [
        { opacity: 1, transform: "none" },
        { opacity: 0, transform: "translateY(8px) scale(.99)" },
      ],
      { duration: 160, easing: "cubic-bezier(.4,0,1,1)" },
    ).finished.finally(() => {
      delete d.dataset.closing;
      d.close();
    });
  }
  ["detail-dialog", "overlay-dialog"].forEach((id) => {
    const d = $(`#${id}`);
    d.addEventListener("cancel", (e) => {
      e.preventDefault();
      closeModal(d);
    });
    d.addEventListener("click", (e) => {
      if (e.target !== d) return;
      const r = d.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        closeModal(d);
    });
  });
  window.addEventListener("hashchange", () => {
    if ($("#overlay-dialog").open) $("#overlay-dialog").close();
    if ($("#detail-dialog").open) $("#detail-dialog").close();
    render(true);
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener(
    "change",
    applyTheme,
  );
  $$("[data-icon]").forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
  applyTheme();
  render();
})();
