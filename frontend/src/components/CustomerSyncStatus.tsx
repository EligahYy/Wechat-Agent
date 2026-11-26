import { AlertCircle, Check, RefreshCw } from "lucide-react";
import type { Operation } from "../api/types";
import { active, operationTitle } from "../app/useOperations";

export function CustomerSyncStatus({operation,error,submitting,onStop,onDetails}:{
  operation:Operation|null;error:string;submitting:boolean;onStop:()=>void;onDetails:(operation:Operation)=>void;
}) {
  if (!operation && !error) return null;
  const running = active(operation);
  const counts = operation?.counts;
  const source = operation?.phase === "source" || (!running && !counts?.analysis_material_total);
  const total = (source ? counts?.conversations_total : counts?.analysis_material_total) || 0;
  const completed = (source ? counts?.completed_conversations : counts?.analysis_material_completed) || 0;
  const progressText = source ? `已同步 ${completed} / ${total} 个会话` : `已校验 ${completed} / ${total} 条原文`;
  return <section className="customer-sync-status" role="region" aria-label="当前客户同步状态">
    <div className="customer-sync-summary" role="status">
      {running ? <RefreshCw size={17} className="spin"/> : operation?.state === "succeeded" ? <Check size={17}/> : <AlertCircle size={17}/>}
      <strong>{operation ? operationTitle(operation) : "同步请求未提交"}</strong>
      {total > 0 && <span>{progressText}</span>}
    </div>
    {operation && <div className="customer-sync-actions">
      <button type="button" className="text-button" onClick={()=>onDetails(operation)}>查看同步详情</button>
      {operation.available_actions.includes("stop") && <button type="button" className="text-button" disabled={submitting} onClick={onStop}>停止本次</button>}
    </div>}
    {running && total > 0 && <progress aria-label={source ? "会话同步进度" : "原文整理进度"} value={Math.min(completed,total)} max={total}/>}
    {error && <p className="error-banner" role="alert">{error}</p>}
  </section>;
}
