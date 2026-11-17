ALTER TABLE history_run_units ADD COLUMN superseded INTEGER NOT NULL DEFAULT 0 CHECK(superseded IN (0,1));
CREATE TABLE history_refinements (
 account_id TEXT NOT NULL,
 snapshot_id TEXT NOT NULL,
 parent_id TEXT NOT NULL,
 child_id TEXT NOT NULL,
 CHECK(parent_id!=child_id),
 PRIMARY KEY(account_id,snapshot_id,parent_id,child_id),
 FOREIGN KEY(account_id,snapshot_id,parent_id) REFERENCES history_run_units(account_id,snapshot_id,unit_id),
 FOREIGN KEY(account_id,snapshot_id,child_id) REFERENCES history_run_units(account_id,snapshot_id,unit_id)
);
