CREATE TABLE history_retry_windows (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    failure_code TEXT,
    retry_at REAL NOT NULL,
    rounds INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(account_id, contact_id, cache_key),
    FOREIGN KEY(account_id, contact_id, cache_key)
        REFERENCES history_checkpoints(account_id, contact_id, cache_key) ON DELETE CASCADE
);

ALTER TABLE snapshots ADD COLUMN material_fingerprint TEXT;
