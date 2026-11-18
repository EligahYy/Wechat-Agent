import type { OrganizationStatus, ProfileStatus } from "../../api/types";

export const profileStatusLabels: Record<ProfileStatus, string> = {
  no_data: "暂无资料",
  pending: "待整理",
  no_findings: "未提取到可发布资料",
  manual: "人工资料",
  ready: "已更新",
  incomplete: "整理不完整",
  needs_update: "待更新",
};

export const organizationStatusLabels: Record<OrganizationStatus, string> = {
  queued: "已排队",
  syncing: "正在同步",
  organizing: "正在整理",
  stop_requested: "正在停止",
  stopped: "已停止",
  paused: "整理已暂停",
  no_findings: "本次未提取到可发布资料",
  source_incomplete: "来源同步未完成",
  failed: "整理未完成",
  updated: "整理完成",
  unchanged: "资料无需更新",
  partial: "本次整理有待核对项",
  not_applicable: "暂无可整理消息",
};
