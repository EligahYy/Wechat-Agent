CREATE TABLE snapshots (
    account_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY(account_id,snapshot_id),
    FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE INDEX snapshots_contact ON snapshots(account_id,contact_id,created_at);
