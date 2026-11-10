"""Persistent per-customer stop token, shared by manual and queued runs."""

import fcntl
import os
from contextlib import contextmanager

from .store import stable


def lock_path(db, source_id):
    return db.settings.data_dir / (
        "workspace-" + stable(db.settings.source_account, source_id) + ".lock"
    )


def running(db, source_id):
    """A historical status row alone does not prove an executor is alive."""
    try:
        fd = os.open(lock_path(db, source_id), os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


@contextmanager
def command_lock(db, source_id):
    """Serialize short state transitions, never hold this during a model call."""
    fd = os.open(
        lock_path(db, source_id).with_suffix(".command.lock"),
        os.O_CREAT | os.O_RDWR,
        0o600,
    )
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def state(db, source_id):
    rows = db.rows(
        "SELECT user_paused,control_version FROM workspace_queue WHERE account_id=? AND source_id=?",
        (db.settings.source_account, source_id),
    )
    return rows[0] if rows else {"user_paused": 0, "control_version": 0}
