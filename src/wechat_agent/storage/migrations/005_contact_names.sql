ALTER TABLE contacts ADD COLUMN metadata_current INTEGER NOT NULL DEFAULT 0 CHECK(metadata_current IN (0,1));
ALTER TABLE contacts ADD COLUMN metadata_seen_at TEXT;
ALTER TABLE conversations ADD COLUMN provenance TEXT NOT NULL DEFAULT 'unknown'
    CHECK(provenance IN ('session','metadata_candidate','group_directory','unknown'));
ALTER TABLE contacts ADD COLUMN remark_state TEXT NOT NULL DEFAULT 'unknown' CHECK(remark_state IN ('known','empty','unreadable','unknown'));
ALTER TABLE contacts ADD COLUMN nickname_state TEXT NOT NULL DEFAULT 'unknown' CHECK(nickname_state IN ('known','empty','unreadable','unknown'));
UPDATE contacts SET remark_state=CASE WHEN length(trim(COALESCE(remark,'')))>0 THEN 'known' ELSE 'unknown' END,
    nickname_state=CASE WHEN length(trim(COALESCE(nickname,'')))>0 THEN 'known' ELSE 'unknown' END;

CREATE TABLE contact_names (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK(origin IN ('group_member','session_sender')),
    conversation_id TEXT NOT NULL,
    value TEXT,
    state TEXT NOT NULL CHECK(state IN ('known','empty','unreadable','unknown')),
    observed_at TEXT NOT NULL,
    current INTEGER NOT NULL DEFAULT 1 CHECK(current IN (0,1)),
    PRIMARY KEY(account_id,contact_id,origin,conversation_id),
    FOREIGN KEY(account_id,conversation_id) REFERENCES conversations(account_id,conversation_id)
);
CREATE INDEX contact_names_lookup ON contact_names(account_id,contact_id,current);

CREATE TABLE source_group_members (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    current INTEGER NOT NULL DEFAULT 1 CHECK(current IN (0,1)),
    PRIMARY KEY(account_id,conversation_id,contact_id),
    FOREIGN KEY(account_id,conversation_id) REFERENCES conversations(account_id,conversation_id)
);
CREATE INDEX source_group_member_lookup ON source_group_members(account_id,contact_id,current);

CREATE TABLE source_metadata_status (
    account_id TEXT PRIMARY KEY NOT NULL REFERENCES accounts(account_id),
    observed_at TEXT NOT NULL,
    source_mode TEXT NOT NULL,
    patch_id TEXT,
    source_version TEXT,
    generation INTEGER,
    resolver_generation INTEGER,
    source_refreshed_at TEXT,
    people_seen INTEGER NOT NULL,
    name_read_errors INTEGER NOT NULL,
    groups_unreadable INTEGER NOT NULL
);
