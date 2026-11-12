CREATE TABLE import_previews (
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    preview_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('ready','committed')),
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    PRIMARY KEY(account_id,preview_id)
);
CREATE INDEX import_preview_expiry ON import_previews(account_id,state,expires_at);
