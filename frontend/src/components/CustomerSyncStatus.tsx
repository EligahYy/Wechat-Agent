import {HistoryProgress} from './HistoryProgress';
import { AlertCircle, Check, RefreshCw } from "lucide-react";
import type { Operation } from "../api/types";
import { active, operationTitle } from "../app/useOperations";

export function CustomerSyncStatus({operation,error,submitting,onStop,onDetails}:{
  operation:Operation|null;error:string;submitting:boolean;onStop:()=>void;onDetails:(operation:Operation)=>void;
}) {
  if(!operation&&!error)return null;
  const running=active(operation),total=operation?.counts.conversations_total||0;
  const completed=operation?.counts.completed_conversations||0;
  return <section className="customer-sync-status" role="region" aria-label="当前客户同步状态">
    <div className="customer-sync-summary" role="status">
      {running?<RefreshCw size={17} className="spin"/>:operation?.state==='succeeded'?<Check size={17}/>:<AlertCircle size={17}/>}
      <div><strong>{operation?operationTitle(operation):'同步请求未提交'}</strong>
        {operation&&<p>已完成 {completed} / {total} 个会话 · 已读取 {operation.counts.pages_processed||0} 页 · 新增 {operation.counts.inserted||0} 条</p>}
      </div>
    </div>
    {operation&&running&&operation.phase==='source'&&total>0&&<progress aria-label="会话同步进度" value={Math.min(completed,total)} max={total}/>}
    {operation&&<HistoryProgress counts={operation.counts} state={operation.state}/>}
    {operation?.error_code==='capability_not_ready'&&<p className="muted">本次仅完成消息同步，客户档案尚未更新。</p>}
    {error&&<p className="error-banner" role="alert">{error}</p>}
    {operation&&<div className="customer-sync-actions">
      <button type="button" className="text-button" onClick={()=>onDetails(operation)}>查看同步详情</button>
      {operation.available_actions.includes('stop')&&<button type="button" className="text-button" disabled={submitting} onClick={onStop}>停止本次</button>}
    </div>}
  </section>;
}
