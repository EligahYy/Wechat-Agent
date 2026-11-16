import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { OperationDetails } from "./OperationDetails";
import type { Operation } from "../api/types";
const operation: Operation = {
  id: "job-1",
  scope: { account_id: "acct-1", contact_id: null },
  action: "sync",
  state: "failed",
  source_state: "failed",
  phase: "source",
  counts: {
    inserted: 0,
    unchanged: 12,
    conversations_total: 3,
    completed_conversations: 2,
    failed_conversations: 1,
    incomplete_conversations: 0,
  },
  remaining: 1,
  error_code: "source_incomplete",
  available_actions: [],
  updated_at: "2026-11-12T00:00:00Z",
  history_complete: false,
  items: [
    {
      phase: "source",
      state: "failed",
      error_code: "source_incomplete",
      gaps: ["message_sender_invalid"],
    },
  ],
};
it("explains partial source failure without invalidating completed conversations", () => {
  render(<OperationDetails operation={operation} />);
  expect(screen.getByText("目标会话 3")).toBeVisible();
  expect(screen.getByText("已完成 2")).toBeVisible();
  expect(screen.getByText("未完成 1")).toBeVisible();
  expect(screen.getByText(/发送人标识异常/)).toBeVisible();
});
it("does not interpret history_complete false alone as failed sync", () => {
  render(
    <OperationDetails
      operation={{
        ...operation,
        state: "succeeded",
        source_state: "succeeded",
        error_code: null,
        counts: {
          conversations_total: 3,
          completed_conversations: 3,
          failed_conversations: 0,
        },
        items: [],
      }}
    />,
  );
  expect(screen.getByText("本次来源同步已完成")).toBeVisible();
  expect(screen.queryByText("来源同步不完整")).not.toBeInTheDocument();
});
it("reports metadata refresh separately from chat synchronization", () => {
  render(<OperationDetails operation={{...operation, action: "refresh_contacts", state: "succeeded", source_state: "succeeded", error_code: null, items: [], counts: {metadata_people: 12, metadata_groups: 3, names_scoped: 2, names_missing: 1}}} />);
  expect(screen.getByText("联系人资料已刷新")).toBeVisible();
  expect(screen.getByText("来源资料 12 条")).toBeVisible();
  expect(screen.getByText("群资料 3")).toBeVisible();
  expect(screen.getByText("群内／会话名称 2")).toBeVisible();
  expect(screen.queryByText(/目标会话|新增 0/)).not.toBeInTheDocument();
});
it("explains the persisted archive partition rather than subtracting source rows", () => {
  render(<OperationDetails operation={{...operation,action:"refresh_contacts",state:"succeeded",source_state:"succeeded",items:[],counts:{metadata_people:12,contacts_total:14,contacts_current:11,contacts_retained:3,names_missing:1}}} />);
  expect(screen.getByText("刷新后归档 14 人")).toBeVisible();
  expect(screen.getByText("本次来源收录 11 人")).toBeVisible();
  expect(screen.getByText("其他归档 3 人")).toBeVisible();
  expect(screen.getByText(/待识别.*身份/)).toBeVisible();
});

it('retains metadata refresh statistics when a new report is present',()=>{
 render(<OperationDetails operation={{...operation,action:'refresh_contacts',state:'succeeded',source_state:'succeeded',counts:{metadata_people:10,metadata_groups:2,names_missing:1},report:{version:1,scope_label:'全部范围',source_outcome:'completed',analysis_outcome:'not_applicable',contacts:[],issues:[]}}}/>);
 expect(screen.getByText('来源资料 10 条')).toBeVisible();
 expect(screen.queryByText(/0\/0 个会话/)).not.toBeInTheDocument();
});
