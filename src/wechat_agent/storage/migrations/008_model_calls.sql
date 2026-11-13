CREATE TABLE analysis_units (
    account_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0 CHECK(requests BETWEEN 0 AND 6),
    PRIMARY KEY(account_id,unit_id),
    FOREIGN KEY(account_id,snapshot_id) REFERENCES snapshots(account_id,snapshot_id),
    FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE TABLE model_calls (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    config_version TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    finish_reason TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(usage_json)),
    model_id TEXT NOT NULL,
    PRIMARY KEY(account_id,unit_id,attempt),
    FOREIGN KEY(account_id,unit_id) REFERENCES analysis_units(account_id,unit_id),
    FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
