import { useEffect, useState } from "react";
import { messageFor, request } from "../api/client";
import type { Operation } from "../api/types";

export type ReviewRef = {message_id: string; revision: number};
type Entry = ReviewRef & {preview: string; day: string; conversation_id: string};
type Page = {items: Entry[]; total: number; sources: Record<string, {title: string}>};

const PAGE_SIZE = 20;
const SELECTION_LIMIT = 100;

export function RelevanceReview({operation, onReview}: {operation: Operation; onReview: (refs: ReviewRef[]) => void}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page>();
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<ReviewRef[]>([]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      account_id: operation.scope.account_id, reviewable_only: "true", page: String(page),
    });
    setError("");
    setData(undefined);
    request<Page>(`/api/operations/${encodeURIComponent(operation.id)}/relevance?${params}`, {signal:controller.signal})
      .then(result => {if (!controller.signal.aborted) setData(result);})
      .catch(reason => {if (!controller.signal.aborted) setError(messageFor(reason));});
    return () => controller.abort();
  }, [operation.id, operation.scope.account_id, open, page]);

  const count = operation.counts.relevance_reviewable;
  return <details className="relevance-review" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>待复核原文{count !== undefined && `（${count}）`}</summary>
    {open && <>
      {error ? <p role="alert">{error}</p> : !data ? <p role="status">正在读取待复核原文…</p> : data.total === 0 ?
        <p className="muted">暂无需要人工复核的原文。</p> : <>
        <ul>
          {data.items.map(entry => {
            const checked = selected.some(item => item.message_id === entry.message_id);
            return <li key={entry.message_id}>
              <label>
                <input type="checkbox" checked={checked} disabled={!checked && selected.length >= SELECTION_LIMIT}
                  onChange={event => setSelected(current => event.target.checked
                    ? [...current, {message_id:entry.message_id, revision:entry.revision}]
                    : current.filter(item => item.message_id !== entry.message_id))}/>
                <span>{entry.preview}
                  <span className="source-line">{entry.day}{data.sources[entry.conversation_id]?.title && ` · ${data.sources[entry.conversation_id].title}`}</span>
                </span>
              </label>
            </li>;
          })}
        </ul>
        <div className="operation-facts">
          {data.total > PAGE_SIZE && <>
            <button className="text-button" disabled={page <= 1} onClick={()=>setPage(page-1)}>上一页</button>
            <span className="muted">{page} / {Math.ceil(data.total / PAGE_SIZE)} 页</span>
            <button className="text-button" disabled={page * PAGE_SIZE >= data.total} onClick={()=>setPage(page+1)}>下一页</button>
          </>}
          <button className="button secondary" disabled={!selected.length} onClick={()=>onReview(selected)}>
            整理所选原文（{selected.length}）
          </button>
        </div>
      </>}
    </>}
  </details>;
}
