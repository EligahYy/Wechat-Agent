"""Short-lived thread-owned connections and atomic, versioned migrations."""

from importlib.resources import files
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 1
_MIGRATIONS = ((1, "001_archive.sql"),)


def open_db(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
    except BaseException:
        conn.close()
        raise
    return conn


def _execute_script(conn: sqlite3.Connection, script: str) -> None:
    # executescript() would commit the caller's migration before running it.
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("incomplete_migration_statement")


def migrate(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("migration_requires_idle_connection")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
                        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                        version INTEGER NOT NULL CHECK(version>0))""")
        row = conn.execute("SELECT version FROM schema_version WHERE singleton=1").fetchone()
        current = row[0] if row else 0
        if current > SCHEMA_VERSION:
            raise RuntimeError("database_schema_newer_than_app")
        for version, name in _MIGRATIONS:
            if version <= current:
                continue
            script = files("wechat_agent.storage").joinpath("migrations", name).read_text(encoding="utf-8")
            _execute_script(conn, script)
            conn.execute("""INSERT INTO schema_version(singleton, version) VALUES (1, ?)
                            ON CONFLICT(singleton) DO UPDATE SET version=excluded.version""", (version,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
