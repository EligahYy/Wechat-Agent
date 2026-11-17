import type {Operation,OperationIssue} from '../api/types';
export const scopeLabel=(o:Operation)=>o.contact_name_snapshot || o.report?.scope_label || (o.scope.contact_id?`联系人（${o.scope.contact_id.replace(/@[^@]+$/, '').slice(-6)}）`:'全部范围');
export function reportTitle(o:Operation):string|null {
 if(o.action==='refresh_contacts')return null;
 if(!o.report||['queued','running','stop_requested'].includes(o.state))return null;
 if(o.state==='stopped')return '任务已停止';
 const r=o.report;
 if(o.action==='sync')return r.source_outcome==='completed'?'原文同步完成':'原文同步未完成';
 return ({updated:'整理完成',unchanged:'输入未变化，无需更新',partial:o.scope.contact_id?'资料已更新，仍有待核对项':'部分客户已整理，仍有未完成项',failed:r.source_outcome==='completed'?'消息已同步，整理未完成':'未能整理',not_applicable:o.action==='refresh_contacts'?'联系人资料已刷新':'暂无可整理资料',not_started:'未能整理',stopped:'任务已停止',running:'正在整理资料'} as Record<string,string>)[r.analysis_outcome];
}
export const reasonLabels:Record<string,string>={model_output_limit_rejected:'供应商拒绝了单次输出额度，请按该模型官方最大输出要求调整；上下文容量不等于输出额度。',history_merge_incomplete:'归纳未保留已有的有效字段或批次，已拒绝该次归纳；重新同步可复用提取结果并重试。',history_merge_unit_too_large:'某个字段或批次的事实仍超出处理容量，提取结果已保留，尚未发布新档案。',context_fixed_overhead_exceeded:'模型窗口不足以容纳固定规则和输出预留，请核对上下文与输出设置。',context_reference_too_large:'必要的引用原文仍超出单段容量，未截断引用，已有分段结果保留。',context_message_overhead_exceeded:'单条消息的必要信息超过处理容量，未截断归档原文。',history_coverage_incomplete:'仍有未完成分段，本次未发布新档案。',chunk_source_outside_unit:'模型引用超出本段已读取范围，已拒绝该段结果。',merge_scope_invalid:'归纳结果超出指定字段或批次范围，已拒绝该结果。',checkpoint_invalid:'保存的分段结果无法校验，本次未发布新档案。',source_conversation_unavailable:'部分已知关联会话本次未能读取，已有资料保留；请检查微信来源后重试。',source_version_unverified:'来源工具版本不符合当前约定，请按指南升级。',credential_unavailable:'无法读取模型密钥，请在模型设置中检查。',credential_store_unsupported:'当前环境不支持所需的密钥存储，请检查运行环境。',model_config_missing:'尚未保存模型配置，请先配置模型。',model_config_changed:'模型配置版本不一致，本次结果未发布。',model_identity_mismatch:'服务返回的模型标识与配置不符，本次未发布。',output_truncated:'模型输出被长度限制截断，本次未发布。',output_schema_invalid:'模型输出不符合资料结构，本次未发布。',model_retry_limit:'模型服务重试次数已达限制，请稍后重试。',retry_after_exceeds_deadline:'模型服务要求的等待时间超出本次任务期限，请稍后重试。',call_request_limit:'本次模型请求次数已达限制，已停止追加请求。',unit_request_limit:'该分段或归纳单元累计请求已达6次上限，继续重试不会追加调用，已有成功结果保留。',request_invalid:'模型服务拒绝了本次请求，请检查模型ID、响应格式与输出上限。',identity_pending:'该联系人身份尚待确认，本次未生成商家档案。',role_not_merchant:'该身份仅保留沟通资料，不参与商家档案整理。',no_material:'暂无可整理消息，可在同步到消息后再整理。',history_complete_unverified:'本次依据已归档原文整理，未验证全部历史覆盖。',attachment_not_processed:'部分附件尚未解析，资料仅依据可用文本。',reply_unavailable:'部分引用消息暂不可用。',profile_field_invalid:'部分字段未通过原文证据校验，已保留可验证的资料。',shipment_field_invalid:'部分备货记录未通过校验，未覆盖其旧事实。',analysis_review_required:'部分资料仍需核对，请查看诊断详情。',analysis_failed:'模型整理未完成，已有资料保留。',capability_not_ready:'尚未配置可用模型，请在设置中配置后重试。',model_timeout:'模型响应超时，已有资料保留。',authentication_failed:'模型服务鉴权失败，请检查API密钥。',rate_limited:'模型服务限流，请稍后重试。',model_not_found:'模型ID不可用，请检查模型配置。',model_temporary_error:'模型服务暂时不可用，请稍后重试。',classification_failed:'业务意图识别未完成，联系人仍保留待识别状态。',output_invalid:'模型输出格式不符合资料约定，本次未发布。',target_mismatch:'模型输出客户不匹配，本次未发布。',material_changed:'原文已更新，本次旧结果未覆盖。',scope_changed:'业务范围已变化，本次结果未发布。',contact_changed:'联系人身份已变化，本次结果未发布。',profile_changed:'已有更新版本，本次旧结果未覆盖。',source_group_membership_unverified:'无法确认是否还有其他关联群，已按已知范围处理。',source_not_complete:'已知会话仍有未解决的读取或消息异常，本次未整理该客户。',source_timeout:'读取关联会话超时。',source_unreachable:'无法连接来源服务。',source_metadata_changed:'读取期间来源资料发生变化，请重新同步。',model_budget_unverified:'请在设置中核对模型文本预算。',model_connection_unverified:'请在设置中检查模型连接。',context_requires_chunking:'历史超出处理预算，需要分段处理。',manual_changed:'人工资料已变化，本次结果未覆盖。',scope_excluded:'客户已被移出业务范围，本次结果未发布。',empty_result:'模型没有提取出可发布的事实，已有资料保留。',retained_evidence_unavailable:'旧资料证据暂时无法验证，已保留原档案。'};
function outcomeTone(o:Operation,issues:OperationIssue[]):string {
 if(['queued','running','stop_requested'].includes(o.state))return 'active';
 if(o.state==='stopped')return 'neutral';
 if(o.action!=='refresh_contacts'&&o.report){
   const outcome=o.action==='sync'?o.report.source_outcome:o.report.analysis_outcome;
   if(outcome==='partial')return 'warning';
   if(['failed','not_started'].includes(outcome))return 'error';
 }
 if(o.state==='failed')return 'error';
 if(issues.some(i=>i.severity==='warning'&&i.stage==='publication'))return 'warning';
 return o.state==='succeeded'?'success':'neutral';
}
export function presentOperation(o:Operation){
 const r=o.report;
 const issues=[...(r?.issues||[]),...(r?.contacts.flatMap(c=>c.issues)||[])];
 const unique=[...new Map(issues.map(i=>[`${i.code}:${i.contact_id||''}:${i.conversation_id||''}`,i])).values()].sort((a,b)=>Number(a.severity==='warning')-Number(b.severity==='warning'));
 const primary=unique.find(i=>i.severity==='blocker');
 return {title:reportTitle(o),scopeLabel:scopeLabel(o),issues:unique,reasonText:primary?(reasonLabels[primary.code]||'本次处理未完成，请查看诊断详情。'):'',action:primary?.suggested_action&&primary.suggested_action!=='none'?primary.suggested_action:null,tone:outcomeTone(o,unique)};
}
export function historyScopeLabel(operation:Operation,peers:Operation[]):string {
 const label=scopeLabel(operation),id=operation.scope.contact_id;
 if(!id)return label;
 const ids=new Set(peers.filter(p=>scopeLabel(p)===label&&p.scope.contact_id).map(p=>p.scope.contact_id!));
 if(ids.size<2)return label;
 let length=Math.max(6,...[...ids].map(v=>v.includes('@')?v.length-v.lastIndexOf('@')+6:6));
 while(length<Math.max(...[...ids].map(v=>v.length))&&new Set([...ids].map(v=>v.slice(-length))).size<ids.size)length++;
 return `${label}（${id.slice(-length)}）`;
}
