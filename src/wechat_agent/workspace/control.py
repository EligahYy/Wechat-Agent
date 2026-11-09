"""Persistent per-customer stop token, shared by manual and queued runs."""


def state(db, source_id):
    rows = db.rows(
        "SELECT user_paused,control_version FROM workspace_queue WHERE account_id=? AND source_id=?",
        (db.settings.source_account, source_id),
    )
    return rows[0] if rows else {"user_paused": 0, "control_version": 0}
