ALTER TABLE operations ADD COLUMN request_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(request_json));
ALTER TABLE operations ADD COLUMN worker_id TEXT;
ALTER TABLE operation_items ADD COLUMN counts_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(counts_json));
ALTER TABLE operation_items ADD COLUMN gaps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(gaps_json));
ALTER TABLE operation_items ADD COLUMN role_version INTEGER CHECK(role_version IS NULL OR role_version>0);
CREATE INDEX operations_dispatch ON operations(state,created_at);
