ALTER TABLE operations ADD COLUMN contact_name_snapshot TEXT;
CREATE TABLE operation_reports (
 account_id TEXT NOT NULL,
 operation_id TEXT NOT NULL,
 report_json TEXT NOT NULL,
 PRIMARY KEY(account_id,operation_id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
