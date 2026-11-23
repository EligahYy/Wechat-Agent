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

it("shows a resumable timeout with the events that preceded it", () => {
  render(<OperationDetails operation={{
    ...operation, action:"sync_and_organize", error_code:"model_timeout", source_state:"succeeded",
    available_actions:["resume"], counts:{source_checkpoint_reused:1, model_attempt_initial:1,
      model_attempt_format_repair:1, model_failure_output_invalid:1, model_failure_model_timeout:1},
    report:{version:1,scope_label:"商家甲",source_outcome:"completed",analysis_outcome:"failed",
      contacts:[],issues:[{code:"model_timeout",stage:"model",severity:"blocker",scope:"contact",suggested_action:"retry_sync"}]},
  }} onAction={() => {}} />);
  expect(screen.getByText(/本次复用已同步的原文/)).toBeInTheDocument();
  expect(screen.getByText(/格式修复 1 次/)).toBeInTheDocument();
  expect(screen.getByText(/格式无效 1 次.*响应超时 1 次/)).toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"重新同步"})).not.toBeInTheDocument();
});
