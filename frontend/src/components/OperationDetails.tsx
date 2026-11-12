import type { Operation } from "../api/types";
import { operationTitle } from "../app/useOperations";

const gapLabels: Record<string, string> = {
  source_patch_required: "来源需安装项目固定版本的 wx-cli 补丁。",
  source_metadata_changed: "读取期间联系人资料代次发生变化，请重新刷新。",
  source_metadata_refresh_failed: "来源联系人资料刷新失败，已有归档仍保留。",
  source_metadata_refresh_timeout: "来源联系人资料刷新超时，请检查来源服务后重试。",
  source_metadata_refresh_unsupported: "当前来源不支持独立刷新联系人。",
  source_metadata_refreshing: "来源正在刷新联系人资料，请稍后重试。",
  source_name_read_failed: "部分名称读取失败，保留旧值并标明来源状态。",
  source_group_members_unreadable: "部分群成员资料无法读取，群内名称保留旧值。",
  source_group_members_unavailable: "群成员资料暂时不可用，无法确认全部关联群聊。",
  message_sender_conflict: "消息发送人证据冲突，原文与候选均保留，暂不归入联系人。",
  message_sender_invalid:
    "发送人标识异常：异常原文已隔离，需修复来源解析后重读。",
  message_sender_missing: "部分消息缺少发送人，尚未归入联系人。",
  message_contract_invalid: "部分消息格式不符合约定，原始数据已保留。",
  source_message_id_unavailable: "部分消息缺少稳定编号，无法可靠归档。",
  source_contact_identity_invalid:
    "联系人元数据包含异常标识，已隔离并保留原始数据。",
  source_rows_skipped: "来源跳过了部分记录，本次读取存在缺口。",
  source_shards_unavailable: "部分消息数据分片不可用。",
  source_page_limit_reached: "已达到本次读取页数上限，会话尚未读完。",
  source_page_no_progress: "来源重复返回同页记录，已停止读取以避免循环。",
  source_cursor_no_progress: "来源游标未前进，尚未完成读取。",
  source_empty_page_with_more: "来源返回空页，但仍提示有后续记录。",
  source_cursor_page_size_mismatch: "续读页大小与已保存游标不一致。",
  source_group_membership_unverified:
    "已读取已知关联会话，来源尚不能确认该客户的全部群聊覆盖范围。",
  source_contact_unavailable: "该联系人尚无可用的来源关联信息。",
  source_metadata_partial: "联系人或会话元数据读取不完整。",
  source_metadata_page_limit_reached: "联系人或会话元数据达到读取上限。",
  source_metadata_no_progress: "联系人或会话元数据分页未前进。",
  source_contract_invalid: "来源返回格式与当前接入约定不符。",
  source_changed_during_sync: "读取期间来源账号或服务状态发生变化。",
  source_account_mismatch: "来源账号与当前配置不一致。",
  source_not_ready: "来源服务尚未就绪。",
  source_timeout: "来源请求超时。",
  source_unreachable: "暂时无法连接来源服务。",
  archive_write_failed: "原文归档写入失败。",
};

export function OperationDetails({ operation }: { operation: Operation }) {
  const metadataOnly = operation.action === "refresh_contacts";
  const counts = operation.counts;
  const total = counts.conversations_total || 0;
  const completed = counts.completed_conversations || 0;
  const unfinished = Math.max(
    0,
    total - completed,
    (counts.failed_conversations || 0) + (counts.incomplete_conversations || 0),
  );
  const gaps = [
    ...new Set(
      (operation.items || [])
        .filter((item) => item.phase === "source")
        .flatMap((item) => item.gaps),
    ),
  ];
  return (
    <section className="operation-detail">
      <h3>{operationTitle(operation)}</h3>
      {metadataOnly ? <div className="operation-facts">
        <span className="info-chip">联系人资料 {counts.metadata_people || 0}</span>
        <span className="info-chip">群资料 {counts.metadata_groups || 0}</span>
        <span className="info-chip">群内／会话名称 {counts.names_scoped || 0}</span>
        <span className="info-chip">尚无名称 {counts.names_missing || 0}</span>
      </div> : <><div className="operation-facts">
        <span className="info-chip">新增 {counts.inserted || 0}</span>
        <span className="info-chip">修订 {counts.revised || 0}</span>
        <span className="info-chip">不变 {counts.unchanged || 0}</span>
      </div>
      <div className="operation-facts">
        <span>目标会话 {total}</span>
        <span>已完成 {completed}</span>
        <span>未完成 {unfinished}</span>
      </div></>}
      <p className="muted">
        来源阶段：
        {operation.source_state === "succeeded"
          ? "已完成"
          : operation.source_state === "failed"
            ? "未完成"
            : operation.source_state === "stopped"
              ? "已停止"
              : "处理中"}
        {operation.error_code === "capability_not_ready"
          ? " · 分析能力尚未接入"
          : ""}
      </p>
      {gaps.length > 0 && (
        <div className="operation-gaps">
          <h4>本次来源缺口</h4>
          <ul>
            {gaps.map((gap) => (
              <li key={gap}>
                {gapLabels[gap] || "来源返回了尚未说明的异常。"}
                {/^[a-z0-9_]{1,80}$/.test(gap) && <code>{gap}</code>}
              </li>
            ))}
          </ul>
          <p className="muted">
            {metadataOnly ? "已有名称和人工身份仍保留；刷新只读取联系人和来源资料。" : "已完成会话的原文仍然保留；来源缺口不等同于新增消息数量。"}
          </p>
        </div>
      )}
      {!gaps.length && operation.source_state === "failed" && (
        <p className="muted">
          此记录未保存具体来源缺口，无法仅凭完成数量判断原因。
        </p>
      )}
    </section>
  );
}
