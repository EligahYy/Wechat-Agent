import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { SelectField } from "./SelectField";
import { Dialog } from "./Dialog";

function Example({disabled=false}:{disabled?:boolean}) {
  const [value,setValue]=useState('all');
  return <><SelectField label="消息来源" value={value} disabled={disabled} onValueChange={setValue}
    options={[{value:'all',label:'全部来源'},{value:'private',label:'私信'},{value:'group',label:'群聊'}]}/>
    <output aria-label="选定来源">{value}</output><button>外部按钮</button></>;
}
it('chooses from a custom list and preserves the controlled value until confirmation',async()=>{
  const user=userEvent.setup();render(<Example/>);
  const trigger=screen.getByRole('combobox',{name:'消息来源'});
  await user.click(trigger);
  expect(screen.getByRole('listbox')).toBeVisible();
  expect(screen.getByRole('option',{name:'全部来源'})).toHaveAttribute('aria-selected','true');
  await user.keyboard('{ArrowDown}');
  expect(screen.getByLabelText('选定来源')).toHaveTextContent('all');
  await user.keyboard('{Enter}');
  expect(screen.getByLabelText('选定来源')).toHaveTextContent('private');
  await waitFor(()=>expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
});
it('dismisses without changing value and consumes Escape before the parent dialog',async()=>{
  const user=userEvent.setup(),close=vi.fn();
  render(<Dialog open title="客户详情" onClose={close}><Example/></Dialog>);
  const trigger=screen.getByRole('combobox',{name:'消息来源'});
  await user.click(trigger);await user.keyboard('{End}{Escape}');
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByLabelText('选定来源')).toHaveTextContent('all');
  await waitFor(()=>expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
  await user.click(trigger);await user.click(screen.getByRole('button',{name:'外部按钮'}));
  await waitFor(()=>expect(screen.queryByRole('listbox')).not.toBeInTheDocument());
  expect(screen.getByLabelText('选定来源')).toHaveTextContent('all');
});
it('does not open when disabled',async()=>{
  const user=userEvent.setup();render(<Example disabled/>);
  await user.click(screen.getByRole('combobox'));
  expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
});
it('removes an exiting menu from navigation when the next field opens',async()=>{
  const user=userEvent.setup();
  const options=[{value:'a',label:'第一列'},{value:'b',label:'第二列'}];
  render(<><SelectField label="会话" value="a" options={options} onValueChange={()=>{}}/>
    <SelectField label="作者" value="a" options={options} onValueChange={()=>{}}/></>);
  await user.click(screen.getByRole('combobox',{name:'会话'}));
  await user.click(screen.getByRole('option',{name:'第二列'}));
  await user.click(screen.getByRole('combobox',{name:'作者'}));
  expect(screen.getAllByRole('listbox')).toHaveLength(1);
  expect(screen.getAllByRole('option',{name:'第二列'})).toHaveLength(1);
});
