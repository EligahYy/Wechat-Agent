CREATE TABLE profile_heads (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 0 CHECK(version>=0),
 manual_version INTEGER NOT NULL DEFAULT 0 CHECK(manual_version>=0),
 PRIMARY KEY(account_id,contact_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE TABLE profile_versions (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL, version INTEGER NOT NULL,
 snapshot_id TEXT NOT NULL, candidate_json TEXT NOT NULL CHECK(json_valid(candidate_json)),
 result_json TEXT NOT NULL CHECK(json_valid(result_json)), issues_json TEXT NOT NULL CHECK(json_valid(issues_json)),
 complete INTEGER NOT NULL CHECK(complete IN (0,1)), pending INTEGER NOT NULL CHECK(pending IN (0,1)),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(account_id,contact_id,version), UNIQUE(account_id,snapshot_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES profile_heads(account_id,contact_id),
 FOREIGN KEY(account_id,snapshot_id) REFERENCES snapshots(account_id,snapshot_id)
);
CREATE TABLE shipments (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL, shipment_id TEXT NOT NULL,
 stage TEXT NOT NULL CHECK(stage IN ('沟通','询价','方案对接','备货','已走货','已结束','暂缓')),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 numbers_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(numbers_json)),
 PRIMARY KEY(account_id,shipment_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE INDEX shipments_contact ON shipments(account_id,contact_id);
CREATE TABLE shipment_keys (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL, candidate_key TEXT NOT NULL, shipment_id TEXT NOT NULL,
 PRIMARY KEY(account_id,contact_id,candidate_key),
 FOREIGN KEY(account_id,shipment_id) REFERENCES shipments(account_id,shipment_id),
 FOREIGN KEY(account_id,contact_id) REFERENCES contacts(account_id,contact_id)
);
CREATE TABLE shipment_anchors (
 account_id TEXT NOT NULL, contact_id TEXT NOT NULL, anchor TEXT NOT NULL, shipment_id TEXT NOT NULL,
 PRIMARY KEY(account_id,contact_id,anchor),
 FOREIGN KEY(account_id,shipment_id) REFERENCES shipments(account_id,shipment_id)
);
