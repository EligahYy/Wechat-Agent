CREATE TABLE accounts (
    account_id TEXT PRIMARY KEY NOT NULL CHECK(length(trim(account_id))>0),
    display_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE contacts (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL CHECK(length(trim(contact_id))>0 AND contact_id NOT LIKE '%@chatroom'),
    remark TEXT,
    nickname TEXT,
    is_self INTEGER NOT NULL DEFAULT 0 CHECK(is_self IN (0, 1)),
    role TEXT NOT NULL DEFAULT 'unknown' CHECK(role IN ('unknown', 'merchant', 'provider', 'platform')),
    role_version INTEGER NOT NULL DEFAULT 1 CHECK(role_version>0),
    CHECK(is_self=0 OR role='unknown'),
    PRIMARY KEY(account_id, contact_id),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);

CREATE TABLE conversations (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL CHECK(length(trim(conversation_id))>0),
    kind TEXT NOT NULL CHECK(kind IN ('private', 'group')),
    title TEXT,
    PRIMARY KEY(account_id, conversation_id),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);

CREATE TABLE members (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'observed_sender',
    PRIMARY KEY(account_id, conversation_id, contact_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(account_id, contact_id) REFERENCES contacts(account_id, contact_id)
);
CREATE INDEX members_contact ON members(account_id, contact_id);

CREATE TABLE messages (
    account_id TEXT NOT NULL,
    message_id TEXT NOT NULL CHECK(length(trim(message_id))>0),
    conversation_id TEXT NOT NULL,
    sender_id TEXT,
    sent_at TEXT NOT NULL CHECK(length(trim(sent_at))>0),
    kind TEXT NOT NULL CHECK(length(trim(kind))>0),
    body TEXT NOT NULL,
    reply_to TEXT,
    source_revision TEXT NOT NULL CHECK(length(trim(source_revision))>0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    CHECK((sender_id IS NOT NULL AND length(trim(sender_id))>0) OR
          (sender_id IS NULL AND kind IN ('system', 'revoke'))),
    PRIMARY KEY(account_id, message_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(account_id, sender_id) REFERENCES contacts(account_id, contact_id)
);
CREATE INDEX messages_chronology ON messages(account_id, conversation_id, sent_at, message_id);
CREATE INDEX messages_sender ON messages(account_id, sender_id, sent_at);

CREATE TABLE message_revisions (
    account_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision>0),
    source_revision TEXT NOT NULL CHECK(length(trim(source_revision))>0),
    sender_id TEXT,
    sent_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    reply_to TEXT,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    archived_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK((sender_id IS NOT NULL AND length(trim(sender_id))>0) OR
          (sender_id IS NULL AND kind IN ('system', 'revoke'))),
    PRIMARY KEY(account_id, message_id, revision),
    FOREIGN KEY(account_id, message_id) REFERENCES messages(account_id, message_id),
    FOREIGN KEY(account_id, sender_id) REFERENCES contacts(account_id, contact_id)
);

CREATE TABLE attachments (
    account_id TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'unfetched'
        CHECK(state IN ('unfetched', 'original', 'thumbnail', 'missing', 'unavailable', 'failed')),
    local_path TEXT,
    mime TEXT,
    sha256 TEXT,
    reason TEXT,
    PRIMARY KEY(account_id, attachment_id),
    FOREIGN KEY(account_id, message_id) REFERENCES messages(account_id, message_id)
);

CREATE TABLE sync_cursors (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    cursor TEXT,
    complete INTEGER NOT NULL DEFAULT 0 CHECK(complete IN (0, 1)),
    gaps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(gaps_json)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY(account_id, conversation_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);

CREATE TABLE sync_attempts (
    account_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running', 'succeeded', 'failed', 'stopped')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_code TEXT,
    gaps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(gaps_json)),
    PRIMARY KEY(account_id, attempt_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);

CREATE TABLE operations (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    contact_id TEXT,
    action TEXT NOT NULL CHECK(length(trim(action))>0),
    idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key))>0),
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued', 'running', 'stop_requested', 'stopped', 'succeeded', 'failed')),
    phase TEXT NOT NULL DEFAULT 'queued',
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation>0),
    remaining INTEGER NOT NULL DEFAULT 0 CHECK(remaining>=0),
    counts_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(counts_json)),
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY(account_id, id),
    UNIQUE(account_id, idempotency_key),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id),
    FOREIGN KEY(account_id, contact_id) REFERENCES contacts(account_id, contact_id)
);

CREATE TABLE operation_items (
    account_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    contact_id TEXT,
    conversation_id TEXT,
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued', 'running', 'stop_requested', 'stopped', 'succeeded', 'failed')),
    phase TEXT NOT NULL DEFAULT 'queued',
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation>0),
    checkpoint_json TEXT CHECK(checkpoint_json IS NULL OR json_valid(checkpoint_json)),
    error_code TEXT,
    PRIMARY KEY(account_id, operation_id, item_id),
    FOREIGN KEY(account_id, operation_id) REFERENCES operations(account_id, id),
    FOREIGN KEY(account_id, contact_id) REFERENCES contacts(account_id, contact_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);

CREATE TABLE settings (
    account_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
    PRIMARY KEY(account_id, name),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);

CREATE VIRTUAL TABLE message_search USING fts5(body, content='messages', content_rowid='rowid', tokenize='trigram');

CREATE TRIGGER messages_search_insert AFTER INSERT ON messages BEGIN
    INSERT INTO message_search(rowid, body) VALUES (new.rowid, new.body);
END;

CREATE TRIGGER messages_search_delete AFTER DELETE ON messages BEGIN
    INSERT INTO message_search(message_search, rowid, body) VALUES ('delete', old.rowid, old.body);
END;

CREATE TRIGGER messages_search_update AFTER UPDATE OF body ON messages BEGIN
    INSERT INTO message_search(message_search, rowid, body) VALUES ('delete', old.rowid, old.body);
    INSERT INTO message_search(rowid, body) VALUES (new.rowid, new.body);
END;
