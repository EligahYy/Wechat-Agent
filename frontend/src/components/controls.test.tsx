import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RoleTag } from "./RoleTag";
import { TimePicker } from "./TimePicker";
import { FormField } from "./FormField";
import { Dialog } from "./Dialog";

describe("shared controls", () => {
  it("shows four distinct role labels", () => {
    render(
      <>
        {(["unknown", "merchant", "provider", "platform"] as const).map(
          (role) => (
            <RoleTag key={role} role={role} />
          ),
        )}
      </>,
    );
    for (const text of ["待识别", "商家", "服务商", "平台"])
      expect(screen.getByText(text)).toBeVisible();
  });
  it("normalizes a typed time on commit and keeps invalid drafts", async () => {
    const save = vi.fn();
    render(<TimePicker value="08:30" onCommit={save} />);
    const field = screen.getByLabelText("每天开始时间");
    fireEvent.change(field, { target: { value: "9:05" } });
    fireEvent.blur(field);
    expect(save).toHaveBeenCalledWith("09:05");
    await waitFor(() => expect(field).toHaveValue("09:05"));
    fireEvent.change(field, { target: { value: "25:70" } });
    fireEvent.blur(field);
    expect(screen.getByRole("alert")).toHaveTextContent("请输入有效时间");
    expect(field).toHaveValue("25:70");
    expect(save).toHaveBeenCalledTimes(1);
  });
  it("cancels panel drafts without saving and restores clock focus", async () => {
    const user = userEvent.setup(),
      save = vi.fn();
    render(<TimePicker value="08:30" onCommit={save} />);
    const trigger = screen.getByRole("button", { name: "选择开始时间" });
    await user.click(trigger);
    expect(screen.getByText("北京时间")).toBeVisible();
    await user.click(screen.getByRole("option", { name: "09 时" }));
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(save).not.toHaveBeenCalled();
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.getByLabelText("每天开始时间")).toHaveValue("08:30");
  });
  it("applies panel selection only after explicit apply", async () => {
    const user = userEvent.setup(),
      save = vi.fn();
    render(<TimePicker value="08:30" onCommit={save} />);
    await user.click(screen.getByRole("button", { name: "选择开始时间" }));
    await user.click(screen.getByRole("option", { name: "09 时" }));
    expect(save).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "应用" }));
    expect(save).toHaveBeenCalledWith("09:30");
  });
  it("uses the same control class for text, multiline, search and time", () => {
    render(
      <>
        <FormField label="货品" />
        <FormField label="备注" multiline />
        <FormField label="搜索" type="search" />
        <TimePicker value="08:30" onCommit={() => {}} />
      </>,
    );
    for (const label of ["货品", "备注", "搜索", "每天开始时间"])
      expect(screen.getByLabelText(label)).toHaveClass("form-control");
    expect(screen.getByLabelText("备注").tagName).toBe("TEXTAREA");
  });
  it("disables both time entry and its picker", () => {
    render(<TimePicker value="08:30" onCommit={() => {}} disabled />);
    expect(screen.getByLabelText("每天开始时间")).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择开始时间" })).toBeDisabled();
  });
  it("contains keyboard focus and closes on Escape", async () => {
    const user = userEvent.setup(),
      close = vi.fn();
    render(
      <Dialog open title="设置身份" onClose={close}>
        <button>确认身份</button>
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await user.keyboard("{Escape}");
    expect(close).toHaveBeenCalledTimes(1);
  });
});

it("labels a contact dialog with its composed heading", () => {
  render(
    <Dialog open title={<span>商家甲</span>} onClose={() => {}}>
      <p>内容</p>
    </Dialog>,
  );
  expect(screen.getByRole("dialog")).toHaveAccessibleName("商家甲");
});
it("keeps time panel keyboard focus inside the draft until dismissal", async () => {
  const user = userEvent.setup();
  render(<TimePicker value="08:30" onCommit={() => {}} />);
  await user.click(screen.getByRole("button", { name: "选择开始时间" }));
  const apply = screen.getByRole("button", { name: "应用" });
  apply.focus();
  await user.tab();
  expect(screen.getByRole("option", { name: "08 时" })).toHaveFocus();
});

it("does not double-save when Enter is followed by blur during a pending commit", () => {
  const save = vi.fn(() => new Promise<void>(() => {}));
  render(<TimePicker value="08:30" onCommit={save} />);
  const input = screen.getByLabelText("每天开始时间");
  fireEvent.change(input, { target: { value: "9:05" } });
  fireEvent.keyDown(input, { key: "Enter" });
  fireEvent.blur(input);
  expect(save).toHaveBeenCalledTimes(1);
});
it("opening the clock with typed text creates a draft and cancellation restores the saved time", async () => {
  const user = userEvent.setup(),
    save = vi.fn();
  render(<TimePicker value="08:30" onCommit={save} />);
  const input = screen.getByLabelText("每天开始时间");
  await user.clear(input);
  await user.type(input, "9:05");
  await user.click(screen.getByRole("button", { name: "选择开始时间" }));
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByRole("option", { name: "09 时" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(input).toHaveValue("08:30");
});

it("puts customer actions in the dialog header beside close", () => {
  render(
    <Dialog
      open
      title="客户资料"
      onClose={() => {}}
      headerActions={<button>同步此客户</button>}
    >
      <p>资料正文</p>
    </Dialog>,
  );
  const button = screen.getByRole("button", { name: "同步此客户" });
  expect(
    screen.getByRole("dialog").querySelector(".dialog-header"),
  ).toContainElement(button);
});
