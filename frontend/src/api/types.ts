export type Role = "merchant" | "provider" | "platform" | "unknown";
export type ContactKey = { account_id: string; contact_id: string };
export type Contact = {
  key: ContactKey;
  business_scope: {included:boolean;reasons:string[];provisional:boolean;version:number};
  display_name: string;
  display_name_source: string;
  copy_name: string | null;
  name_status: "current" | "scoped" | "historical" | "last_known" | "missing";
  name_scope: string | null;
  name_conflict: boolean;
  name_reason: string | null;
  metadata_current: boolean;
  metadata_seen_at: string | null;
  role: Role;
  role_version: number;
  sources: {
    conversation_id: string;
    kind: "private" | "group";
    title: string | null;
    provenance: "session" | "metadata_candidate" | "group_directory" | "unknown";
    has_messages: boolean;
    title_state?: "known" | "empty" | "unreadable" | "unknown";
  }[];
  last_message_at: string | null;
  last_business_at: string | null;
  profile_status: "pending" | "no_data" | "manual" | "ready" | "incomplete" | null;
  profile_summary?:{goods:string|null;logistics:string|null;communication:string|null;tags:string[]};
  profile_updated_at: string | null;
  source_gaps: string[];
};
export type ContactPage = {
  items: Contact[];
  total: number;
  page: number;
  page_size: number;
  role_counts: Record<Role | "all", number>;
};
export type Preferences = {
  daily_time: string;
  daily_enabled: boolean;
  appearance: "system" | "light" | "dark";
  reduce_motion: boolean;
};
export type AppSettings = {
  account_id: string | null;
  preferences: Preferences;
  version: number;
  timezone: string;
  source: { state: string };
  model: { state: string; model_id: string | null; connection_state?: string };
  capabilities: { organize: boolean; scheduler: boolean; raw_browser: boolean };
};
export type RoleUpdate = {
  status: string;
  updated: { key: ContactKey; role: Role; role_version: number }[];
  failed: { key: ContactKey; code: string; current_version: number | null }[];
};
export type Operation = {
  id: string;
  scope: { account_id: string; contact_id: string | null };
  action: string;
  state:
    | "queued"
    | "running"
    | "stop_requested"
    | "stopped"
    | "succeeded"
    | "failed";
  source_state: string | null;
  phase: string;
  counts: Record<string, number>;
  remaining: number;
  error_code: string | null;
  available_actions: string[];
  updated_at: string;
  history_complete: false;
  items?: {
    phase: string;
    state: string;
    error_code: string | null;
    gaps: string[];
  }[];
};
export type TimelineItem = {
  message_id:string;conversation_id:string;source_title:string|null;source_kind:"private"|"group";
  sender:{contact_id:string|null;display_name:string;role:Role|null;is_self:boolean;identity_state:string;name_status?:string};
  sent_at:string;kind:string;body:string;revision:number;reply_to:string|null;origin:"import"|"archive";
  attachments:{id:string;state:string;mime:string|null;reason:string|null;downloadable:boolean}[];
};
export type SpeechPosition = {current_id:string;index:number;previous_id:string|null;next_id:string|null};
export type SpeechNavigation = {total:number;current_id:string|null;index:number;previous_id:string|null;next_id:string|null;positions?:SpeechPosition[]};
export type TimelinePage = {speech?:SpeechNavigation;previous_cursor?:string|null;items:TimelineItem[];total:number;sources:{conversation_id:string;kind:string;title:string|null}[];next_cursor:string|null;has_more:boolean;timezone:string};
export type ImportPreview = {
  preview_id:string|null;columns:string[];sample_rows:Record<string,string>[];total_rows:number;mapping_defaults:Record<string,string>;
  counts?:{valid:number;rejected:number;new:number;unchanged:number;total:number};
  issues:{row:number;code:string}[];issues_truncated?:boolean;
  sample_messages?:{row:number;sender_id:string|null;conversation_id:string;sent_at:string;body:string;status:string}[];
};
export type ImportResult = {status:string;preview_id:string;already_committed:boolean;counts:{inserted:number;unchanged:number;rejected:number;total:number};issues:{row:number;code:string}[]};
