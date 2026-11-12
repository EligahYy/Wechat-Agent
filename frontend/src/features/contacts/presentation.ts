import type { Contact } from "../../api/types";
export function nameNotice(contact: Contact): string | null {
  if (contact.name_status === "scoped")
    return contact.name_conflict ? "多来源名称" : contact.display_name_source === "group_member" ? "群内名称" : "会话名称";
  if (contact.name_status === "historical") return "历史名称";
  if (contact.name_reason === "name_read_failed") return "名称读取失败，保留旧值";
  if (contact.name_status === "last_known") return "名称待核实";
  if (contact.name_status === "missing") return contact.name_reason === "source_name_empty" ? "来源未提供名称" : "名称信息未确认";
  return null;
}
export function sourceLabel(source: Contact["sources"][number]) {
  if (source.kind === "group") return `${source.title || "群名称缺失"}${source.title_state === "unreadable" ? "（名称读取失败）" : ""} · ${source.has_messages ? "群聊记录" : "群来源"}`;
  if (source.has_messages) return "私聊记录";
  if (source.provenance === "session") return "最近私聊";
  return source.provenance === "metadata_candidate" ? "联系人资料" : "历史来源";
}
export function avatarText(name: string) {
  return new Intl.Segmenter("zh", { granularity: "grapheme" }).segment(name)[Symbol.iterator]().next().value?.segment || "?";
}
