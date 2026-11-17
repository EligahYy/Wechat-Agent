export function HistoryProgress({counts,state}:{counts:Record<string,number>;state:string}) {
 const total=counts.analysis_chunks_total||0,completed=counts.analysis_chunks_completed||0;
 if(total<=1&&!counts.analysis_merge_total)return null;
 return <div className="history-progress" role="group" aria-label="长历史整理进度">
   <p>分段提取 {completed} / {total} · 复用 {counts.analysis_chunks_reused||0} 段</p>
   <progress aria-label="长历史提取进度" value={Math.min(completed,total)} max={Math.max(1,total)}/>
   {!!counts.analysis_refinements&&<p>输出范围已拆小 {counts.analysis_refinements} 次</p>}
   {!!counts.analysis_merge_total&&<p>事实归纳 {counts.analysis_merge_completed||0} / {counts.analysis_merge_total}</p>}
   {!!counts.analysis_material_total&&<p className="muted">已处理 {counts.analysis_material_completed||0} / {counts.analysis_material_total} 条原文</p>}
   {['failed','stopped','stop_requested'].includes(state)&&<p className="muted">已完成分段已保留，重新同步将复用有效结果。</p>}
 </div>;
}
