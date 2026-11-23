CREATE TABLE message_relevance (
    account_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    PRIMARY KEY(account_id,snapshot_id),
    FOREIGN KEY(account_id,snapshot_id) REFERENCES snapshots(account_id,snapshot_id),
    FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE INDEX message_relevance_operation ON message_relevance(account_id,operation_id);
CREATE INDEX message_relevance_contact ON message_relevance(account_id,contact_id);
CREATE TABLE relevance_receipts (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('unchanged','no_relevant_material')),
    PRIMARY KEY(account_id,contact_id),
    FOREIGN KEY(account_id,snapshot_id) REFERENCES message_relevance(account_id,snapshot_id)
);
