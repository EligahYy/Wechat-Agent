CREATE TABLE model_budget_reviews (
 account_id TEXT NOT NULL,
 config_version INTEGER NOT NULL,
 reference TEXT NOT NULL,
 capabilities_json TEXT NOT NULL CHECK(json_valid(capabilities_json)),
 reviewed_at TEXT NOT NULL,
 PRIMARY KEY(account_id,config_version),
 FOREIGN KEY(account_id,config_version) REFERENCES model_config_versions(account_id,version)
);
