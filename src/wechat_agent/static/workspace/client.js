export const $ = (s) => document.querySelector(s);
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const time = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        timeZone: "Asia/Shanghai",
        hour12: false,
      })
    : "—";
export async function api(path, body) {
  const response = await fetch(
    path.startsWith("/") ? path : "/api/workspace/" + path,
    {
      method: body ? "POST" : "GET",
      headers: body
        ? {
            "Content-Type": "application/json",
            "X-CSRF-Token": $("meta[name=csrf]").content,
          }
        : {},
      body: body ? JSON.stringify(body) : undefined,
    },
  );
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "请求未完成，请重试");
  return data;
}
export function notice(text) {
  const target = $("dialog")?.open ? $("#detail-status") : $("#status");
  if (target) target.textContent = errorText(text);
}
export async function copy(text) {
  if (!navigator.clipboard) throw Error("浏览器未开放剪贴板，请选中文字后复制");
  await navigator.clipboard.writeText(text);
  notice("已复制。请核对后在微信中手动发送。");
}

export function errorText(code) {
  if (code?.startsWith("workspace_fact_schema"))
    return (
      "资料分册格式未通过校验。已整理的分册保留；点击重试分析可继续。" +
      (code.includes(":") ? " 字段：" + code.split(":").slice(1).join(":") : "")
    );
  return (
    {
      workspace_fact_truncated:
        "模型返回被截断；重试时将拆成更小的分册，保留已有进度。",
      workspace_summary_not_reduced:
        "本轮分册合并未缩减，已保留全部资料。请重试分析。",
      workspace_customer_paused: "该客户已暂停，请在整理进度中点击继续分析。",
      customer_paused: "该客户已手动暂停，点击继续分析即可续跑。",
      call_limit: "本轮分册已保存，后台将继续；也可点击继续分析。",
      automation_paused: "自动整理已暂停；可继续这位客户。",
      HTTP_401: "模型认证失败，请检查 API key。",
      HTTP_402: "模型账户余额不足，请充值后继续。",
      HTTP_429: "模型请求限流，将稍后重试。",
      ConnectError: "无法连接 DeepSeek，请检查网络与本机代理。",
      workspace_clue_not_pending:
        "这条线索已被处理，请重新打开档案查看最新结果。",
      workspace_clue_not_resolved: "这条线索已恢复，请查看待核实列表。",
      workspace_clue_verification_required:
        "请填写核对后的资料，并确认它属于当前客户。",
      workspace_draft_running:
        "这位客户的草稿正在准备，请稍后查看，无需重复生成。",
      workspace_draft_not_ready:
        "这项行动目前不能生成草稿。请先处理新进展、确认归属或恢复联系建议。",
      workspace_draft_schema: "草稿未通过来源检查，未采用；可查看原文后重试。",
      workspace_stale_input: "来源或人工判断已变化，请刷新档案后重新操作。",
      workspace_stale_evidence: "这份档案的来源已修订，请等待重新整理后查看。",
      workspace_confirmation_required: "请先核对来源并确认由我跟进。",
      workspace_ocr_version_conflict:
        "图片文字已被更新，本次修改未保存。请重新打开图片核对。",
      workspace_invalid_ocr_text: "请填写需要核对的图片文字，最多20000字。",
      workspace_ocr_unavailable:
        "未找到本机识别工具，可以对照图片手动填写文字。",
      workspace_ocr_failed:
        "本机识别未完成。请检查识别工具，或手动填写核对文字。",
      workspace_ocr_empty: "未识别到文字，请查看原图并手动填写。",
      workspace_source_not_allowed:
        "当前账号无权读取此来源，请检查绑定账号和会话范围。",
      workspace_stage_note_required: "请填写人工阶段判断的依据。",
      workspace_version_conflict:
        "档案已被更新，本次修改未保存。请重新打开后核对。",
      workspace_followup_note_required: "请填写实际跟进内容。",
      blocked_credentials: "请在设置中检查DeepSeek key和文本分析授权。",
      blocked_budget: "此任务来自旧版预算暂停，更新服务后点击继续分析。",
    }[code] || code
  );
}
