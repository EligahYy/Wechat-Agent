import { $, esc, api, notice, time } from "./client.js";
import { renderWhitelist } from "./whitelist.js";
let account, probe, pendingFile;
const active = () => $("[data-view=settings][aria-current=page]");
export async function renderSettings() {
  const data = await api("settings");
  if (!active()) return;
  account = data.account_id;
  const max = Math.max(1, ...data.week.map((d) => d.reported + d.uncertain));
  $("#content").innerHTML =
    `<div id="settings-view" class="settings-grid"><section class="card"><h2>工作微信与本机连接</h2><p>${esc(data.account_name || "尚未同步昵称")} <span class="meta">${esc(account || "尚未绑定工作账号")}</span></p><p class="muted">只读采集，微信消息仍由你发送。连接检测不调用模型。</p><div class="toolbar spaced"><button id="probe-work-account">检测微信连接</button><button id="sync-work-names" ${account ? "" : "disabled"}>刷新联系人与群名</button></div><div id="binding-result"></div><div id="monitor-cards" role="status">正在检查本机状态…</div><button id="monitor-refresh" class="spaced">重新检测状态</button></section>
<section class="card"><h2>DeepSeek 与分析授权</h2><p>${esc(data.model)} · ${data.key_configured ? "已配置 key" : "尚未配置 key"} · ${data.transport.route === "explicit_http_proxy" ? "通过已配置的本机代理连接" : "使用当前网络配置"}</p><form id="workspace-key-form"><label>更新 API key<input name="key" type="password" minlength="10" maxlength="500" autocomplete="new-password" required placeholder="输入新 key；已有 key 不会回显"></label><button>保存 key</button></form>${data.key_source === "environment" ? '<p class="meta">当前优先使用环境变量中的 key；保存到系统后，需移除旧环境变量并重启才能切换。</p>' : ""}<form id="workspace-policy-form" class="spaced"><label class="check-label"><input type="checkbox" name="enabled" ${data.policy.enabled ? "checked" : ""}>允许将已授权工作聊天文本交给 DeepSeek 分析</label><label class="check-label"><input type="checkbox" name="include_new" ${data.policy.include_new ? "checked" : ""}>新发现的工作会话沿用账号分析授权（白名单仍排除）</label><button class="primary">保存授权</button></form><p class="meta">今日已报告 ${data.budget.reported.toLocaleString()} token · 未确认预留 ${data.budget.uncertain.toLocaleString()}。只统计用量，不设每日 Token 上限；自动整理开关在“数据大屏”。</p></section>
<section id="whitelist" class="card settings-wide"><h2>免跟进白名单</h2><p class="muted">人物与会话仅保留归档，不在数据大屏和跟进栏显示，也不产生客户跟进任务。</p><div id="whitelist-manager"></div></section>
<section class="card"><h2>近七天用量</h2><p class="muted">按北京时间统计 token；浅色部分为未确认预留，不等于实际扣费。</p><div class="usage-chart" role="img" aria-label="近七天 token 用量">${data.week.map((d) => `<div class="usage-day" title="${esc(d.day)}：已报告 ${d.reported}，未确认 ${d.uncertain}"><div class="usage-column"><i style="height:${(100 * d.reported) / max}%"></i><b style="height:${(100 * d.uncertain) / max}%"></b></div><small>${esc(d.day.slice(5))}</small><span>${(d.reported + d.uncertain).toLocaleString()}</span></div>`).join("")}</div></section>
<section class="card"><h2>归档与图片</h2><p>已归档 ${data.archive.messages} 条消息 · 图片 ${data.archive.images || 0} 条</p><p>${esc(data.ocr.note)}${data.ocr.engine ? " · " + esc(data.ocr.engine) : ""}</p><p class="meta">图片先在本机查看；识别文字经人工核对后才进入下一轮分析。原图不会发送给 DeepSeek。</p><details class="spaced"><summary>补充导入聊天记录</summary><p class="meta">可选入口，仅支持 CSV、JSON、JSONL（最大750KB）。需要来源消息ID、会话ID、发送者ID、带时区时间和正文；格式见部署文档。导入按当前账号授权和白名单处理。</p><label>选择文件<input id="workspace-import-file" type="file" accept=".csv,.json,.jsonl,.ndjson"></label><div id="import-preview"></div></details></section></div>`;
  await Promise.all([monitor(), renderWhitelist()]);
  if (location.hash === "#whitelist")
    $("#whitelist")?.scrollIntoView({ block: "start" });
}
async function monitor() {
  const data = await api("/api/monitor");
  const target = $("#monitor-cards");
  if (!active() || !target) return;
  target.innerHTML = data.checks
    .map(
      (c) =>
        `<article class="monitor-row"><span class="status-dot ${esc(c.state)}"></span><div><strong>${esc(c.name)}</strong><p>${esc(c.detail)}</p>${c.updated_at ? `<small>${esc(time(c.updated_at))} 北京时间</small>` : ""}</div></article>`,
    )
    .join("");
}
document.addEventListener("submit", async (e) => {
  if (!["workspace-key-form", "workspace-policy-form"].includes(e.target.id))
    return;
  e.preventDefault();
  const button = e.target.querySelector("button");
  button.disabled = true;
  try {
    const f = new FormData(e.target);
    if (e.target.id === "workspace-key-form") {
      await api("/api/crm/credentials", { key: f.get("key") });
      e.target.reset();
      notice("key 已保存到系统凭据存储。");
    } else {
      await api("/api/crm/configure", {
        enabled: f.has("enabled"),
        include_new: f.has("include_new"),
      });
      await api("queue/refresh", {});
      notice("分析授权已保存。");
    }
  } catch (error) {
    notice(error.message);
  } finally {
    button.disabled = false;
  }
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (
    ![
      "probe-work-account",
      "bind-work-account",
      "sync-work-names",
      "monitor-refresh",
      "write-message-file",
    ].includes(b.id)
  )
    return;
  b.disabled = true;
  try {
    if (b.id === "probe-work-account") {
      probe = await api("/api/source/probe", {});
      $("#binding-result").innerHTML =
        `<div class="insight-card"><strong>${esc(probe.account_name)}</strong><p class="meta">${esc(probe.account_id)}</p>${probe.bound ? "<p>当前工作账号已绑定。</p>" : '<button id="bind-work-account">确认绑定这个工作账号</button>'}</div>`;
    } else if (b.id === "bind-work-account") {
      if (!probe) return;
      await api("/api/source/bind", { account_id: probe.account_id });
      await renderSettings();
      notice("工作账号已绑定。");
    } else if (b.id === "sync-work-names") {
      const results = await Promise.allSettled([
        api("/api/identity/sync", {}),
        api("/api/source/names/refresh", {}),
      ]);
      notice(
        results.every((r) => r.status === "fulfilled")
          ? "联系人与群名已刷新。"
          : "部分名称刷新未完成，请检查微信源服务。",
      );
    } else if (b.id === "monitor-refresh") await monitor();
    else if (b.id === "write-message-file") {
      if (!pendingFile) return;
      const result = await api("/api/imports/file", {
        ...pendingFile,
        write: true,
      });
      $("#import-preview").textContent =
        `已导入 ${result.inserted || 0} 条，重复 ${result.duplicates || 0} 条；后续按当前自动整理开关运行。`;
      pendingFile = null;
    }
  } catch (error) {
    notice(error.message);
  } finally {
    if (b.isConnected) b.disabled = false;
  }
});
document.addEventListener("change", async (e) => {
  if (e.target.id !== "workspace-import-file") return;
  pendingFile = null;
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (!account) throw Error("请先绑定工作账号");
    if (file.size > 750 * 1024)
      throw Error("单文件最大750KB；更大文件请拆分或使用命令行导入");
    const payload = {
      filename: file.name,
      text: await file.text(),
      account_id: account,
    };
    const result = await api("/api/imports/file", payload);
    if (result.rejected) {
      $("#import-preview").innerHTML =
        `<p>有 ${result.rejected} 行需要修正，本次未写入。</p>${result.errors.map((x) => `<p class="meta">第${x.row}行：${esc(x.error)}</p>`).join("")}`;
      return;
    }
    pendingFile = payload;
    $("#import-preview").innerHTML =
      `<p>可导入 ${result.valid} 条，涉及 ${result.conversations} 个会话。</p><button id="write-message-file" ${result.valid ? "" : "disabled"}>确认导入记录</button>`;
  } catch (error) {
    notice(error.message);
  }
});
