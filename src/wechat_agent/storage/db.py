"""Short-lived thread-owned connections and atomic, versioned migrations."""

from importlib.resources import files
from pathlib import Path
import sqlite3
from ..identities import is_person_identifier


SCHEMA_VERSION = 15
_MIGRATIONS = ((1, "001_archive.sql"), (2, "002_source_sync.sql"), (3, "003_operations.sql"), (4, "004_identity_integrity.sql"), (5, "005_contact_names.sql"), (6, "006_import_previews.sql"), (7, "007_context_snapshots.sql"), (8, "008_model_calls.sql"), (9, "009_model_settings.sql"), (10, "010_business_scope.sql"), (11, "011_message_query_indexes.sql"), (12, "012_profile_publication.sql"), (13, "013_manual_profiles.sql"), (14, "014_model_budget_reviews.sql"), (15, "015_operation_reports.sql"))


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


def open_existing_db(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Runtime requests use an existing database; only explicit startup may create it."""
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(Path(path).resolve().as_uri() + f"?mode={mode}", uri=True, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
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
    conn.create_function("wechat_person_id_valid", 1, lambda value: int(is_person_identifier(value)), deterministic=True)
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
