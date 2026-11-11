CREATE TABLE source_issues (
    account_id TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    message_id TEXT,
    source_revision TEXT NOT NULL,
    code TEXT NOT NULL,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    resolved INTEGER NOT NULL DEFAULT 0 CHECK(resolved IN (0, 1)),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY(account_id, issue_id),
    UNIQUE(account_id, conversation_id, message_id, source_revision, code),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);

CREATE TABLE sync_leases (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    expires_at REAL NOT NULL,
    PRIMARY KEY(account_id, conversation_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);
