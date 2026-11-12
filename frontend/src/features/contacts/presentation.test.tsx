import { expect, it } from "vitest";
import { nameNotice, sourceLabel, avatarText } from "./presentation";
import type { Contact } from "../../api/types";
it("does not label contact-directory candidates as private chat records", () => {
  expect(sourceLabel({kind:"private", provenance:"metadata_candidate", has_messages:false, title:"甲", conversation_id:"person"})).toBe("联系人资料");
  expect(sourceLabel({kind:"private", provenance:"session", has_messages:false, title:"甲", conversation_id:"person"})).toBe("最近私聊");
  expect(sourceLabel({kind:"group", provenance:"group_directory", has_messages:true, title:"业务群", conversation_id:"room"})).toBe("业务群 · 群聊记录");
});
it("explains scoped, historical and unreadable names without implying current friends", () => {
  expect(nameNotice({name_status:"scoped",display_name_source:"group_member"} as Contact)).toBe("群内名称");
  expect(nameNotice({name_status:"historical"} as Contact)).toBe("历史名称");
  expect(nameNotice({name_status:"last_known",name_reason:"name_read_failed"} as Contact)).toBe("名称读取失败，保留旧值");
});
it("keeps emoji graphemes intact in avatars", () => {
  expect(avatarText("👨‍👩‍👧‍👦之家")).toBe("👨‍👩‍👧‍👦");
});
