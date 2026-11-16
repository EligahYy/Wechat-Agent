CREATE TABLE history_runs (
 account_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 operation_id TEXT NOT NULL,
 strategy TEXT NOT NULL,
 estimator TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('direct','chunked')),
 materials_json TEXT NOT NULL CHECK(json_valid(materials_json)),
 context_tokens INTEGER NOT NULL,
 progress_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(progress_json)),
 PRIMARY KEY(account_id,snapshot_id),
 FOREIGN KEY(account_id,snapshot_id) REFERENCES snapshots(account_id,snapshot_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE INDEX history_runs_operation ON history_runs(account_id,operation_id);
CREATE TABLE history_checkpoints (
 account_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 cache_key TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('extract','merge')),
 state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','failed')),
 requests INTEGER NOT NULL DEFAULT 0 CHECK(requests BETWEEN 0 AND 6),
 output_json TEXT CHECK(output_json IS NULL OR json_valid(output_json)),
 error_code TEXT,
 PRIMARY KEY(account_id,contact_id,cache_key),
 FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE TABLE history_run_units (
 account_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 contact_id TEXT NOT NULL,
 unit_id TEXT NOT NULL,
 cache_key TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('extract','merge')),
 ordinal INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','failed')),
 reused INTEGER NOT NULL DEFAULT 0 CHECK(reused IN (0,1)),
 input_tokens INTEGER NOT NULL,
 output_tokens INTEGER NOT NULL,
 primary_json TEXT NOT NULL CHECK(json_valid(primary_json)),
 request_json TEXT NOT NULL CHECK(json_valid(request_json)),
 error_code TEXT,
 PRIMARY KEY(account_id,snapshot_id,unit_id),
 FOREIGN KEY(account_id,snapshot_id) REFERENCES history_runs(account_id,snapshot_id),
 FOREIGN KEY(account_id,contact_id,cache_key) REFERENCES history_checkpoints(account_id,contact_id,cache_key)
);
CREATE INDEX history_units_cache ON history_run_units(account_id,contact_id,cache_key);
