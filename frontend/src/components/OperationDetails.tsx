import {HistoryProgress} from './HistoryProgress';
import {reasonLabels,presentOperation} from '../app/operationOutcome';
import { metadataTotals } from "../app/operationPresentation";
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
  source_message_id_unavailable: "微信来源未提供部分消息的稳定编号。这些记录待补齐，可重新读取相关会话。",
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

export function OperationDetails({ operation,onAction }: { operation: Operation;onAction?:(action:string)=>void }) {
  if(operation.action!=='refresh_contacts' && operation.report && !['queued','running','stop_requested'].includes(operation.state)) {
    const report=operation.report;
    const presentation=presentOperation(operation);
    const unique=presentation.issues;
    const notApplicable=report.contacts.filter(c=>c.analysis_outcome==='not_applicable'&&c.reason&&reasonLabels[c.reason]);
    return <section className="operation-detail"><h3>{operationTitle(operation)}</h3>
      <div className="operation-facts">
        <span className="info-chip">新增 {operation.counts.inserted||0}</span>
        <span className="info-chip">修订 {operation.counts.revised||0}</span>
        <span className="info-chip">不变 {operation.counts.unchanged||0}</span>
      </div>
      <HistoryProgress counts={operation.counts} state={operation.state}/>
      <div className="operation-outcomes"><p>消息同步：{{completed:'已完成（已知范围）',partial:(operation.counts.conversations_total>0&&operation.counts.completed_conversations>=operation.counts.conversations_total)?'会话已读取，仍有消息异常':'部分完成',failed:'未完成',stopped:'已停止',not_started:'未开始'}[report.source_outcome]||'处理中'} · {operation.counts.completed_conversations||0}/{operation.counts.conversations_total||0} 个会话</p>
      <p>资料整理：{operationTitle(operation)}</p></div>
      {(unique.length>0||notApplicable.length>0||report.analysis_outcome==='failed'||presentation.action)&&<div className="operation-gaps"><h4>本次处理提示</h4>
      {notApplicable.map(c=><p key={c.contact_id}>{reasonLabels[c.reason!]}</p>)}
      {[...new Map(unique.map(i=>[i.code,i])).values()].slice(0,2).map((i,n)=><p key={n}>{i.severity==='warning'?(i.stage==='publication'?'待核对':'范围提示'):'原因'}：{reasonLabels[i.code]||gapLabels[i.code]||'本次处理遇到异常，可展开诊断详情查看。'}</p>)}
      {report.analysis_outcome==='failed'&&<p>本次未更新的客户保留已有资料，可根据原因重新同步或检查模型设置。</p>}
      {presentation.action&&onAction&&<button className="text-button" onClick={()=>onAction(presentation.action!)}>{presentation.action==='open_model_settings'?'检查模型设置':presentation.action==='review_contact'?'检查联系人':'重新同步'}</button>}
      </div>}
      {report.contacts.length>1&&<ul className="operation-customer-results">{report.contacts.map(c=><li key={c.contact_id}>{c.name_snapshot||c.contact_id} · {c.analysis_outcome==='failed'?'未完成':c.analysis_outcome==='partial'?'已更新，需核对':c.analysis_outcome==='updated'?'已更新':c.analysis_outcome==='unchanged'?'无需更新':'未执行'}</li>)}</ul>}
      <details className="operation-diagnostics"><summary>诊断详情</summary>{!!(operation.counts.model_source_unknown||operation.counts.model_source_revision_mismatch||operation.counts.model_source_other_unit)&&<p>引用问题：未知编号 {operation.counts.model_source_unknown||0} · 修订不符 {operation.counts.model_source_revision_mismatch||0} · 引用其他段 {operation.counts.model_source_other_unit||0}。仅按当前段合法清单尝试一次纠错，不放宽引用权限。</p>}{!!operation.counts.model_last_output_limit&&<p>最近请求输出上限 {operation.counts.model_last_output_limit} · 输出截断 {operation.counts.model_output_truncations||0} 次{operation.counts.model_last_completion_tokens!==undefined&&` · 返回用量 ${operation.counts.model_last_completion_tokens}`}{operation.counts.model_last_reasoning_tokens!==undefined&&` · 其中推理 ${operation.counts.model_last_reasoning_tokens}`}</p>}{!!operation.counts.analysis_context_tokens&&<p>上下文容量 {operation.counts.analysis_context_tokens} · 最大单元输入估算 {operation.counts.analysis_max_input_tokens||0} · 输出预留 {operation.counts.analysis_max_output_tokens||0} · 安全余量 10%。输入采用 UTF-8 保守上界，非精确 token 数。</p>}{unique.map((i,n)=><p key={n}>{i.stage} · <code>{i.code}</code> {i.field_path} {i.conversation_id}</p>)}{report.contacts.map(c=><p key={c.contact_id}>{c.contact_id} · {c.analysis_outcome} {c.reason}</p>)}</details>
    </section>;
  }
  const metadataOnly = operation.action === "refresh_contacts";
  const counts = operation.counts;
  const archive = metadataTotals(counts);
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
        <span className="info-chip">来源资料 {counts.metadata_people || 0} 条</span>
        <span className="info-chip">群资料 {counts.metadata_groups || 0}</span>
        <span className="info-chip">群内／会话名称 {counts.names_scoped || 0}</span>
        <span className="info-chip">归档姓名缺失 {counts.names_missing || 0} 人</span>
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
      {metadataOnly && archive && <div className="operation-facts">
        <span>刷新后归档 {archive.total} 人</span>
        <span>本次来源收录 {archive.current} 人</span>
        <span>其他归档 {archive.retained} 人</span>
      </div>}
      {metadataOnly && <p className="muted">
        {archive ? "归档人数＝本次来源收录＋其他归档。其他归档为本次联系人资料未包含的沟通或历史人物，不代表当前好友关系。" : "此记录未保存归档人数拆分，来源读取量不代表归档总数。"}
        待识别表示身份尚未确认，与姓名是否缺失无关。
      </p>}
      {!!counts.analysis_required&&<div className="operation-analysis"><h4>资料整理</h4><div className="operation-facts"><span>目标商家 {counts.analysis_required}</span><span>已更新 {counts.analysis_completed||0}</span><span>无需更新 {counts.analysis_skipped||0}</span><span>未完成 {counts.analysis_failed||0}</span></div>{!!counts.analysis_incomplete&&<p className="muted">有 {counts.analysis_incomplete} 位商家的资料已更新，但仍有来源或字段缺口。</p>}{operation.phase==='analysis'&&operation.error_code&&<p className="muted">{{model_budget_unverified:'请在设置中核对供应商文档与文本预算后再整理。',model_connection_unverified:'请先完成模型连接检查。',context_requires_chunking:'历史超出当前处理预算，需要分段处理，已有资料保留。',contact_changed:'客户身份发生变化，本次结果未发布。',manual_changed:'人工资料已变化，旧结果未覆盖。'}[operation.error_code]||'模型整理未完成，已有资料仍保留。'}<code>{operation.error_code}</code></p>}</div>}
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
