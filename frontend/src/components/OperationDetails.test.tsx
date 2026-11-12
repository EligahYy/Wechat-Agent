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
