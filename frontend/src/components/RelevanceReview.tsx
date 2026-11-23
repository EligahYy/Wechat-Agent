import { useEffect, useState } from "react";
import { messageFor, request } from "../api/client";
import type { Operation } from "../api/types";

export type ReviewRef = {message_id: string; revision: number};
type Entry = ReviewRef & {level: "high" | "medium" | "low"; preview: string; day: string; needs_review: boolean;
  usable: boolean; reason_codes: string[]};
type Page = {items: Entry[]; total: number; sources: Record<string, {title: string}>};
const labels = {high: "高", medium: "中", low: "低"};
const reasons: Record<string, string> = {
  field_match:"有匹配的档案字段", linked_reply:"关联业务回复", reviewed:"已加入复核", revocation_review:"撤回记录待核对", ambiguous_recipients:"同时涉及多个客户",
  attachment_unprocessed:"附件待解析", context_required:"需结合语境", other_customer:"属于其他客户",
  greeting_or_reaction:"寒暄或表情", system_event:"系统事件",
};

export function RelevanceReview({operation, onReview}: {operation: Operation; onReview: (refs: ReviewRef[]) => void}) {
  const [open, setOpen] = useState(false), [level, setLevel] = useState("medium");
  const [day, setDay] = useState(""), [room, setRoom] = useState(""), [page, setPage] = useState(1);
  const [data, setData] = useState<Page>(), [error, setError] = useState("");
  const [selected, setSelected] = useState<ReviewRef[]>([]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const params = new URLSearchParams({account_id: operation.scope.account_id, page:String(page)});
    if (level) params.set("level", level);
    if (day) params.set("day", day);
    if (room) params.set("conversation_id", room);
    setError("");
    request<Page>(`/api/operations/${encodeURIComponent(operation.id)}/relevance?${params}`, {signal:controller.signal})
      .then(result => {if (!controller.signal.aborted) setData(result);})
      .catch(reason => {if (!controller.signal.aborted) setError(messageFor(reason));});
    return () => controller.abort();
  }, [operation.id, operation.scope.account_id, open, level, day, room, page]);

  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>查看分级与复核</summary>
    <div className="operation-facts">
      <label>等级 <select value={level} onChange={event => {setLevel(event.target.value);setPage(1);}}>
        <option value="">全部</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option>
      </select></label>
      <label>日期 <input type="date" value={day} onChange={event => {setDay(event.target.value);setPage(1);}}/></label>
      <label>来源 <select value={room} onChange={event => {setRoom(event.target.value);setPage(1);}}>
        <option value="">全部来源</option>
        {Object.entries(data?.sources ?? {}).map(([id, source]) => <option key={id} value={id}>{source.title || id}</option>)}
      </select></label>
    </div>
    {error && <p role="alert">{error}</p>}
    {open && data?.total === 0 && <p>此范围暂无消息</p>}
    {open && data?.items.map(entry => <p key={entry.message_id}>
      <label>
        <input type="checkbox" disabled={entry.level === "high" || entry.reason_codes.some(code=>["other_customer","ambiguous_recipients","system_event","attachment_unprocessed","revocation_review"].includes(code))}
          checked={selected.some(item => item.message_id === entry.message_id)}
          onChange={event => setSelected(current => event.target.checked
            ? [...current, {message_id:entry.message_id, revision:entry.revision}]
            : current.filter(item => item.message_id !== entry.message_id))}/>
        {labels[entry.level]} · {entry.day} · {entry.preview}
      </label>
      <span className="source-line">{entry.reason_codes.map(code => reasons[code] || code).join("、")}</span>
    </p>)}
    <div className="operation-facts">
      <button className="text-button" disabled={page<=1} onClick={()=>setPage(page-1)}>上一页</button>
      <button className="text-button" disabled={!data || page*20>=data.total} onClick={()=>setPage(page+1)}>下一页</button>
      <button className="button secondary" disabled={!selected.length || selected.length>100}
        onClick={()=>onReview(selected)}>整理所选原文（{selected.length}）</button>
    </div>
  </details>;
}
