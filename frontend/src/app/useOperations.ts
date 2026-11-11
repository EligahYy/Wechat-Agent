import { useCallback, useEffect, useRef, useState } from "react";
import { request, ApiError, messageFor } from "../api/client";
import type { Operation } from "../api/types";
export const active = (job: Operation | null) =>
  !!job && ["queued", "running", "stop_requested"].includes(job.state);
export const operationTitle = (job: Operation | null) => {
  if (!job) return "尚无整理记录";
  if (job.state === "queued") return "任务已排队";
  if (job.state === "running")
    return job.phase === "source" ? "正在同步微信原文" : "正在整理资料";
  if (job.state === "stop_requested") return "正在停止本次任务";
  if (job.state === "stopped") return "任务已停止";
  if (job.error_code === "capability_not_ready")
    return "原文已同步，档案整理尚未接入";
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
        if (!active(next)) {
          onDone();
          return;
        }
      } catch (reason) {
        if (controller.signal.aborted) return;
        setError(messageFor(reason));
      }
      timer = setTimeout(() => void poll(), 750);
    };
    timer = setTimeout(() => void poll(), 250);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [account, job?.id, job?.state, read, onDone]);
  const start = async (contactId?: string) => {
    if (!account || lock.current) return;
    lock.current = true;
    setSubmitting(true);
    setError("");
    try {
      const result = await request<Operation>("/api/operations", {
        method: "POST",
        body: JSON.stringify({
          action: contactId ? "sync" : "sync_and_organize",
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
        }
      } else setError(messageFor(reason));
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
    } finally {
      lock.current = false;
      setSubmitting(false);
    }
  };
  return { job, history, submitting, error, start, stop, read, loadHistory };
}
