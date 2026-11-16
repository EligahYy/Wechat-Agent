import { useCallback, useEffect, useRef, useState } from "react";
import { request, ApiError, messageFor } from "../api/client";
import type { ContactKey, Operation } from "../api/types";
import {reportTitle} from './operationOutcome';
export const active = (job: Operation | null) =>
  !!job && ["queued", "running", "stop_requested"].includes(job.state);
export const operationTitle = (job: Operation | null) => {
  if (!job) return "尚无整理记录";
  const title=reportTitle(job);if(title)return title;
  if (job.action === "refresh_contacts")
    return {queued:"联系人刷新已排队", running:"正在刷新联系人资料", stop_requested:"正在停止联系人刷新", stopped:"联系人刷新已停止", failed:"联系人资料刷新未完成", succeeded:"联系人资料已刷新"}[job.state];
  if (job.state === "queued") return "任务已排队";
  if (job.state === "running")
    return job.phase === "source" ? "正在同步微信原文" : "正在整理资料";
  if (job.state === "stop_requested") return "正在停止本次任务";
  if (job.state === "stopped") return "任务已停止";
  if (job.error_code === "capability_not_ready")
    return "原文已同步，档案整理尚未接入";
  if (job.error_code === "model_budget_unverified") return "原文已同步，请核对模型文本预算";
  if (job.error_code === "model_connection_unverified") return "原文已同步，请检查模型连接";
  if (job.error_code === "analysis_incomplete") return "资料已更新，仍有整理缺口";
  if (job.state === "failed" && job.phase === "analysis") return "原文已同步，资料整理未完成";
  if (job.state === "succeeded" && job.action === "sync_and_organize") {
    if (job.counts.analysis_completed) return "同步与资料整理已完成";
    if (job.counts.analysis_skipped) return "原文已同步，资料无需更新";
  }
  if (job.state === "failed")
    return job.error_code === "source_incomplete"
      ? "来源同步不完整"
      : "来源同步未完成";
  return "本次来源同步已完成";
};
export function useOperations(account: string | null, onDone: () => void) {
  const [job, setJob] = useState<Operation | null>(null),
    [history, setHistory] = useState<Operation[]>([]),
    [submitting, setSubmitting] = useState(false),
    [error, setError] = useState("");
  const lock = useRef(false);
  const [errorScope,setErrorScope]=useState<ContactKey|null>(null);
  const loadHistory = useCallback(async () => {
    if (!account) return;
    const result = await request<{ items: Operation[] }>(
      `/api/operations?${new URLSearchParams({ account_id: account })}`,
    );
    setHistory(result.items);
    return result.items;
  }, [account]);
  const read = useCallback(
    async (id: string, signal?: AbortSignal) =>
      request<Operation>(
        `/api/operations/${encodeURIComponent(id)}?${new URLSearchParams({ account_id: account || "" })}`,
        { signal },
      ),
    [account],
  );
  useEffect(() => {
    let cancelled = false;
    setJob(null);
    setError("");setErrorScope(null);
    if (account)
      loadHistory()
        .then((items) => {
          if (!cancelled)
            setJob(items?.find((item) => active(item)) || items?.[0] || null);
        })
        .catch((reason) => {
          if (!cancelled) setError(messageFor(reason));
        });
    return () => {
      cancelled = true;
    };
  }, [account, loadHistory]);
  useEffect(() => {
    if (!account || !active(job)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await read(job!.id, controller.signal);
        if (controller.signal.aborted) return;
        setJob(next);
        setError("");
        setErrorScope(null);
        if (!active(next)) {
          onDone();
          return;
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(messageFor(reason));
        setErrorScope(job?.scope.contact_id ? {account_id:account,contact_id:job.scope.contact_id}:null);
      }
      timer = setTimeout(() => void poll(), 750);
    };
    timer = setTimeout(() => void poll(), 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [account, job?.id, job?.state, read, onDone]);
  const start = async (contactId?: string, action?: "refresh_contacts") => {
    if (!account || lock.current) return;
    lock.current = true;
    setSubmitting(true);
    setError("");
    setErrorScope(null);
    try {
      const result = await request<Operation>("/api/operations", {
        method: "POST",
        body: JSON.stringify({
          action: action || "sync_and_organize",
          scope: {
            account_id: account,
            ...(contactId ? { contact_id: contactId } : {}),
          },
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setJob(result);
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.code === "operation_already_active" &&
        typeof reason.details.operation_id === "string"
      ) {
        try {
          setJob(await read(reason.details.operation_id));
        } catch {
          setError(messageFor(reason));
          setErrorScope(contactId?{account_id:account,contact_id:contactId}:null);
        }
      } else {setError(messageFor(reason));setErrorScope(contactId?{account_id:account,contact_id:contactId}:null);}
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  };
  const stop = async () => {
    if (
      !account ||
      !job ||
      lock.current ||
      !job.available_actions.includes("stop")
    )
      return;
    lock.current = true;
    setSubmitting(true);
    try {
      setJob(
        await request<Operation>("/api/operations", {
          method: "POST",
          body: JSON.stringify({
            action: "stop",
            account_id: account,
            operation_id: job.id,
          }),
        }),
      );
    } catch (reason) {
      setError(messageFor(reason));
      setErrorScope(job.scope.contact_id?{account_id:account,contact_id:job.scope.contact_id}:null);
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  };
  return { job, history, submitting, error, errorScope, start, stop, read, loadHistory };
}
