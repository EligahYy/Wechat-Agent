import type { Operation } from "../api/types";
export function metadataTotals(counts: Operation["counts"]) {
  const total = counts.contacts_total;
  const current = counts.contacts_current;
  const retained = counts.contacts_retained;
  if (![total,current,retained].every(value => Number.isSafeInteger(value) && value >= 0)
      || total !== current + retained) return null;
  return {total,current,retained};
}
export function metadataSummary(operation: Operation) {
  const totals = metadataTotals(operation.counts);
  if (!totals && ["queued","running","stop_requested"].includes(operation.state))
    return "正在读取联系人资料…";
  if (!totals && ["failed","stopped"].includes(operation.state))
    return "本次未完成联系人统计，请查看记录";
  const source = `本次来源资料 ${operation.counts.metadata_people || 0} 条`;
  const missing = `归档姓名缺失 ${operation.counts.names_missing || 0} 人`;
  return totals ? `${source} · 刷新后归档 ${totals.total} 人 · ${missing}` : `${source} · ${missing}`;
}
