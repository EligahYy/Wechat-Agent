import type { Role } from "../api/types";
export const roleNames: Record<Role, string> = {
  unknown: "待识别",
  merchant: "商家",
  provider: "服务商",
  platform: "平台",
};
export function RoleTag({
  role,
  compact = false,
}: {
  role: Role | "self";
  compact?: boolean;
}) {
  return (
    <span className={`role-tag role-${role} ${compact ? "compact" : ""}`}>
      {role === "self" ? "我方" : roleNames[role]}
    </span>
  );
}
