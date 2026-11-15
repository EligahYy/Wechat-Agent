CREATE TABLE profile_manual (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL,
 value_json TEXT NOT NULL CHECK(json_valid(value_json)),
 PRIMARY KEY(account_id,contact_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES profile_heads(account_id,contact_id)
);
CREATE TABLE profile_manual_events (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 kind TEXT NOT NULL CHECK(kind IN ('fields','numbers')), shipment_id TEXT,
 before_json TEXT NOT NULL CHECK(json_valid(before_json)), after_json TEXT NOT NULL CHECK(json_valid(after_json)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(account_id,contact_id,version),
 FOREIGN KEY(account_id,contact_id) REFERENCES profile_heads(account_id,contact_id)
);
ALTER TABLE shipments ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version>0);
ALTER TABLE shipments ADD COLUMN numbers_origin TEXT NOT NULL DEFAULT 'model' CHECK(numbers_origin IN ('model','manual'));
