export class ApiError extends Error {
  constructor(
    public code: string,
    public status: number,
    public details: Record<string, any> = {},
  ) {
    super(code);
  }
}
export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  if (!path.startsWith("/api/") || path.includes("\\") || path.includes("#"))
    throw new ApiError("invalid_api_path", 0);
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new ApiError("invalid_api_response", response.status);
  }
  if (!response.ok)
    throw new ApiError(
      data.code || "request_failed",
      response.status,
      data.details || {},
    );
  return data as T;
}
export const messageFor = (error: unknown) =>
  error instanceof ApiError
    ? {
        message_cursor_stale: "原文已更新，请重新加载",
        message_cursor_invalid: "分页信息已失效，请重新加载",
        messages_not_found: "该联系人的原文不可用",
        archive_not_found: "当前账号下没有这份归档",
        model_version_conflict: "模型配置已变化，请关闭后重新打开以加载最新版本",
        model_new_key_required: "首次配置或更换服务地址时需要填写新密钥",
        credential_unavailable: "无法访问本机 Keychain，请检查钥匙串权限",
        credential_missing: "本机密钥不存在，请重新保存密钥",
        model_check_running: "连接检查正在进行，请稍后查看结果",
        model_check_stale: "检查期间配置已变化，请检查当前新版本",
        model_settings_write_failed: "配置未保存，请稍后重试",
        model_check_failed: "连接检查未完成，请稍后重试",
        import_preview_expired: "预览已过期，请重新预览后导入",
        import_preview_not_found: "预览已失效，请重新预览",
        import_write_failed: "导入未完成，原文已回滚，可重试",
        import_too_large: "文件或请求过大，请使用不超过2MB的文件",
        import_too_many_rows: "文件超过5000行，请拆分后导入",
        import_encoding_invalid: "请使用UTF-8编码的文件",
        import_content_invalid: "文件内容无法解析，请检查CSV或JSON格式",
        import_columns_invalid: "列名缺失、重复或过长，请检查文件",
        import_empty: "文件内没有可导入的记录",
        import_rows_required: "JSON文件需要使用记录数组格式",
        import_request_invalid: "导入信息无效，请重新选择文件并核对字段",
        import_content_type_required: "导入请求格式无效，请刷新页面后重试",
        attachment_not_available: "附件尚未获取或本机文件缺失",
        attachment_not_found: "附件引用不存在",
        settings_version_conflict: "设置已被修改，请刷新后重试",
        account_binding_required: "请先归档微信资料或配置工作账号",
        account_scope_forbidden: "当前工作账号不匹配",
        operation_already_active: "这个范围已有任务正在进行",
        database_unavailable: "本地数据库不可用",
      }[error.code] || "操作未完成，请重试"
    : "连接失败，请确认本地服务已启动";
