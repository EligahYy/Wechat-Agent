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
        settings_version_conflict: "设置已被修改，请刷新后重试",
        account_binding_required: "请先归档微信资料或配置工作账号",
        account_scope_forbidden: "当前工作账号不匹配",
        operation_already_active: "这个范围已有任务正在进行",
        database_unavailable: "本地数据库不可用",
      }[error.code] || "操作未完成，请重试"
    : "连接失败，请确认本地服务已启动";
