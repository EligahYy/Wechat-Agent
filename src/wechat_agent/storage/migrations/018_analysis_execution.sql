CREATE TABLE analysis_execution (
    account_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0 CHECK(requests >= 0),
    PRIMARY KEY(account_id, operation_id),
    FOREIGN KEY(account_id, operation_id) REFERENCES operations(account_id, id) ON DELETE CASCADE
);

ALTER TABLE model_calls ADD COLUMN elapsed_ms INTEGER CHECK(elapsed_ms >= 0);

CREATE TABLE history_reduction_nodes (
    account_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    input_ids_json TEXT NOT NULL CHECK(json_valid(input_ids_json)),
    dispositions_json TEXT NOT NULL CHECK(json_valid(dispositions_json)),
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    output_json TEXT NOT NULL CHECK(json_valid(output_json)),
    PRIMARY KEY(account_id, snapshot_id, node_id),
    FOREIGN KEY(account_id, snapshot_id) REFERENCES history_runs(account_id, snapshot_id) ON DELETE CASCADE
);

CREATE TABLE analysis_workload_feedback (
    account_id TEXT NOT NULL,
    config_version TEXT NOT NULL,
    phase TEXT NOT NULL,
    target INTEGER NOT NULL,
    low_load_streak INTEGER NOT NULL,
    PRIMARY KEY(account_id, config_version, phase),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE analysis_workload_plans (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    config_version TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    window_key TEXT NOT NULL,
    phase TEXT NOT NULL,
    target INTEGER NOT NULL,
    PRIMARY KEY(account_id, contact_id, config_version, conversation_id, window_key, phase),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE history_checkpoint_refs (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    message_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY(account_id, contact_id, cache_key, message_id, revision),
    FOREIGN KEY(account_id, contact_id, cache_key)
        REFERENCES history_checkpoints(account_id, contact_id, cache_key) ON DELETE CASCADE
);
CREATE INDEX history_checkpoint_refs_revision
    ON history_checkpoint_refs(account_id, message_id, revision, contact_id);

CREATE TABLE discovery_checkpoints (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    input_key TEXT NOT NULL,
    PRIMARY KEY(account_id, contact_id),
    FOREIGN KEY(account_id, contact_id) REFERENCES contacts(account_id, contact_id) ON DELETE CASCADE
);
