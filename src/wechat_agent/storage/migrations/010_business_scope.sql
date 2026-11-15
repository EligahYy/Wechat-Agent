CREATE TABLE business_scope_overrides (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    included INTEGER NOT NULL CHECK(included IN (0,1)),
    version INTEGER NOT NULL CHECK(version>0),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(account_id,contact_id),
    FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE TABLE contact_activity (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    PRIMARY KEY(account_id,contact_id),
    FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE TABLE scope_activity_generation (
    account_id TEXT PRIMARY KEY,
    generation TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);
CREATE TABLE business_signals (
    account_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    intent TEXT NOT NULL CHECK(intent IN ('request','advertisement','forwarded','other','uncertain')),
    sources_json TEXT NOT NULL CHECK(json_valid(sources_json)),
    coverage_complete INTEGER NOT NULL CHECK(coverage_complete IN (0,1)),
    observed_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    PRIMARY KEY(account_id,contact_id),
    FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
