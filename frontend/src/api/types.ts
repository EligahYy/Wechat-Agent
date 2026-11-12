export type Role = "merchant" | "provider" | "platform" | "unknown";
export type ContactKey = { account_id: string; contact_id: string };
export type Contact = {
  key: ContactKey;
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
  profile_status: "pending" | "no_data" | null;
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
  model: { state: string; model_id: string | null };
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
