export function HistoryProgress({counts,state}:{counts:Record<string,number>;state:string}) {
 const total=counts.analysis_chunks_total||0,completed=counts.analysis_chunks_completed||0;
 const highValue=counts.relevance_total!==undefined;
 const materialProgress=highValue && (counts.analysis_material_total||0)>0;
 const maximum=materialProgress?counts.analysis_material_total:total;
 const value=materialProgress?(counts.analysis_material_completed||0):completed;
 const waiting=(counts.model_requests_started||0)>(counts.model_requests||0);
 if(total<=1&&!counts.analysis_merge_total&&counts.relevance_total===undefined)return null;
 return <div className="history-progress" role="group" aria-label="长历史整理进度">
   {counts.relevance_total!==undefined&&<p>已筛选 {counts.relevance_total} 条 · 高 {counts.relevance_high||0} · 中 {counts.relevance_medium||0} · 低 {counts.relevance_low||0}</p>}
   {total>0&&<p>分段提取 {completed} / {total} · 复用 {counts.analysis_chunks_reused||0} 段</p>}
   {highValue&&state==="running"&&counts.model_requests_started!==undefined&&<p>模型已请求 {counts.model_requests_started} 次{waiting?" · 等待模型返回":""}</p>}
   {total>0&&<progress aria-label="长历史提取进度" value={Math.min(value,maximum)} max={Math.max(1,maximum)}/>}
   {!!counts.analysis_refinements&&<p>输出范围已拆小 {counts.analysis_refinements} 次</p>}
   {!!counts.analysis_merge_total&&<p>事实归纳 {counts.analysis_merge_completed||0} / {counts.analysis_merge_total}</p>}
   {!!counts.analysis_material_total&&<p className="muted">{counts.relevance_total===undefined?"已处理":"已整理高价值原文"} {counts.analysis_material_completed||0} / {counts.analysis_material_total} 条原文</p>}
   {['failed','stopped','stop_requested'].includes(state)&&<p className="muted">已完成分段已保留，重新同步将复用有效结果。</p>}
 </div>;
}
