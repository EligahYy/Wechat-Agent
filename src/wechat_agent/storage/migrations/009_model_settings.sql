CREATE TABLE model_config_versions (
    account_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version>0),
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    PRIMARY KEY(account_id,version),
    FOREIGN KEY(account_id) REFERENCES accounts(account_id)
);
CREATE TABLE model_connection_checks (
    account_id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    config_version INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('running','passed','failed','interrupted','superseded')),
    code TEXT,
    started_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    finished_at TEXT,
    PRIMARY KEY(account_id,check_id),
    FOREIGN KEY(account_id,config_version) REFERENCES model_config_versions(account_id,version)
);
CREATE UNIQUE INDEX model_check_one_active ON model_connection_checks(account_id) WHERE state='running';
