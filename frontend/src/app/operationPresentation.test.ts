import { expect, it } from "vitest";
import type { Operation } from "../api/types";
import { metadataSummary, metadataTotals } from "./operationPresentation";
const job: Operation = {
  id: "refresh-counts", scope: {account_id:"synthetic",contact_id:null},
  action:"refresh_contacts", state:"succeeded", source_state:"succeeded", phase:"completed",
  counts:{metadata_people:12,names_missing:1,contacts_total:14,contacts_current:11,contacts_retained:3},
  remaining:0, error_code:null, available_actions:[],
  updated_at:"2026-11-12T00:00:00Z", history_complete:false,
};
it("labels source rows and archived people as different totals", () => {
  expect(metadataSummary(job)).toBe("本次来源资料 12 条 · 刷新后归档 14 人 · 归档姓名缺失 1 人");
  expect(metadataTotals(job.counts)).toEqual({total:14,current:11,retained:3});
});
it("does not fabricate a total or retained count for old records", () => {
  const legacy={...job,counts:{metadata_people:12,names_missing:1}};
  expect(metadataTotals(legacy.counts)).toBeNull();
  expect(metadataSummary(legacy)).toBe("本次来源资料 12 条 · 归档姓名缺失 1 人");
});
it("does not display zero archived people before metadata has been read", () => {
  expect(metadataSummary({...job,state:"running",counts:{metadata_people:0}})).toBe("正在读取联系人资料…");
});
it("accepts a verified empty archive but rejects an inconsistent partition", () => {
  expect(metadataTotals({contacts_total:0,contacts_current:0,contacts_retained:0})).toEqual({total:0,current:0,retained:0});
  expect(metadataTotals({contacts_total:14,contacts_current:11,contacts_retained:2})).toBeNull();
});
