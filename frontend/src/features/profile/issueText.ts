export type ProfileIssue = {
  code:string;
  severity:'blocker'|'field_warning'|'coverage_notice'|'business_uncertainty';
  count:number;
  field_path:string|null;
  detail:string|null;
};

export function issueText(issue:ProfileIssue):string {
  switch(issue.code){
    case 'prior_shipment_needs_review':return '旧备货批次的部分来源需重新核对，已保留旧记录';
    case 'retained_evidence_unavailable':return '该字段的旧来源需重新核对';
    case 'attachment_not_processed':return `${issue.count} 个附件尚未解析`;
    case 'history_complete_unverified':return '全部历史覆盖尚未验证';
    case 'reply_unavailable':return `${issue.count} 条引用消息暂不可用`;
    case 'source_message_id_unavailable':return `会话 ${issue.detail ?? ''} 有消息缺少编号，待补齐`;
    case 'number_not_supported':return '原文未支持该数值';
    case 'unit_not_supported':return '原文未支持该单位';
    case 'event_date_not_supported':return '原文未支持该业务日期';
    case 'conflicting_candidates':return '存在不同记录，请核对原文';
    default:return issue.detail || '请核对原文及来源';
  }
}
