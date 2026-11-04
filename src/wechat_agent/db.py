"""SQLite storage with transactional, versioned schema migration."""

import json
import os
import secrets
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

from .config import Settings


def now():
    return datetime.now(UTC).isoformat()


def uid():
    return str(uuid.uuid4())


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants(id TEXT PRIMARY KEY,name TEXT NOT NULL,do_not_contact INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS providers(id TEXT PRIMARY KEY,name TEXT NOT NULL,capabilities TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,merchant_id TEXT NOT NULL REFERENCES merchants(id),name TEXT NOT NULL,market TEXT NOT NULL DEFAULT '',stage TEXT NOT NULL DEFAULT 'needs',version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,source TEXT NOT NULL,account_id TEXT NOT NULL,source_id TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,merchant_id TEXT REFERENCES merchants(id),project_id TEXT REFERENCES projects(id),allowlisted INTEGER NOT NULL DEFAULT 0,egress INTEGER NOT NULL DEFAULT 0,UNIQUE(source,account_id,source_id));
CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),source_id TEXT NOT NULL,sender_id TEXT NOT NULL,direction TEXT NOT NULL,event_time TEXT NOT NULL,text TEXT NOT NULL,type TEXT NOT NULL,completeness TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,ingested_at TEXT NOT NULL,UNIQUE(conversation_id,source_id));
CREATE TABLE IF NOT EXISTS message_revisions(id TEXT PRIMARY KEY,message_id TEXT NOT NULL REFERENCES messages(id),revision INTEGER NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,dedup_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',attempts INTEGER NOT NULL DEFAULT 0,lease_until TEXT,available_at TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS suggestions(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),dedup_key TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,merchant_id TEXT NOT NULL REFERENCES merchants(id),project_id TEXT REFERENCES projects(id),suggestion_id TEXT UNIQUE REFERENCES suggestions(id),summary TEXT NOT NULL,party TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'open',due_at TEXT,due_text TEXT,version INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS touchpoints(id TEXT PRIMARY KEY,merchant_id TEXT NOT NULL REFERENCES merchants(id),project_id TEXT REFERENCES projects(id),outcome TEXT NOT NULL,contacted_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS materials(id TEXT PRIMARY KEY,name TEXT NOT NULL,version TEXT NOT NULL,market TEXT NOT NULL,kind TEXT NOT NULL,terms TEXT NOT NULL,scope TEXT NOT NULL,valid_until TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quotes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),provider_id TEXT NOT NULL REFERENCES providers(id),material_id TEXT REFERENCES materials(id),terms TEXT NOT NULL,confirmed INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS milestones(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),kind TEXT NOT NULL,planned_at TEXT,actual_at TEXT,evidence_type TEXT NOT NULL,note TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sync_windows(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),since INTEGER NOT NULL,until INTEGER NOT NULL,status TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY,job_id TEXT,day TEXT NOT NULL,reserved INTEGER NOT NULL,actual INTEGER,status TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runtime(name TEXT PRIMARY KEY,status TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_time ON messages(conversation_id,event_time);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(status,available_at);
"""


class DB:
    def __init__(self, settings: Settings):
        self.settings = settings.prepare()
        self.path = settings.data_dir / "agent.sqlite3"
        connection = self.connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 4:
                raise ValueError("数据库版本高于当前应用，请升级应用")
            if version == 0:
                connection.executescript(
                    "BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1;COMMIT;"
                )
            if version < 2:
                connection.executescript(
                    "BEGIN IMMEDIATE; CREATE TABLE IF NOT EXISTS contact_roles(conversation_id TEXT NOT NULL REFERENCES conversations(id),sender_id TEXT NOT NULL,role TEXT NOT NULL,display_name TEXT NOT NULL DEFAULT '',PRIMARY KEY(conversation_id,sender_id)); PRAGMA user_version=2; COMMIT;"
                )
            if version < 3:
                connection.executescript(
                    "BEGIN IMMEDIATE; ALTER TABLE messages ADD COLUMN source_locator TEXT NOT NULL DEFAULT '{}'; CREATE TABLE attachments(message_id TEXT PRIMARY KEY REFERENCES messages(id),sha256 TEXT NOT NULL,mime TEXT NOT NULL,quality TEXT NOT NULL,size INTEGER NOT NULL,created_at TEXT NOT NULL); PRAGMA user_version=3; COMMIT;"
                )
            if version < 4:
                connection.executescript(
                    "BEGIN IMMEDIATE; CREATE TABLE archive_progress(conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),until INTEGER NOT NULL,page_offset INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,error TEXT,updated_at TEXT NOT NULL,last_page_hash TEXT NOT NULL DEFAULT ''); CREATE TABLE archive_issues(conversation_id TEXT NOT NULL REFERENCES conversations(id),row_hash TEXT NOT NULL,error TEXT NOT NULL,PRIMARY KEY(conversation_id,row_hash)); CREATE INDEX IF NOT EXISTS messages_sender ON messages(sender_id,conversation_id,event_time); PRAGMA user_version=4; COMMIT;"
                )
        finally:
            connection.close()
        self.path.chmod(0o600)
        token_path = settings.data_dir / "session-token"
        try:
            with open(
                token_path, "x", opener=lambda p, f: __import__("os").open(p, f, 0o600)
            ) as f:
                f.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass

    @property
    def token(self):
        # Reload each request so rotation also revokes already-running sessions.
        return (self.settings.data_dir / "session-token").read_text().strip()

    def rotate_token(self):
        fd, name = tempfile.mkstemp(prefix=".session-", dir=self.settings.data_dir)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_urlsafe(32))
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.settings.data_dir / "session-token")
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def tx(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def rows(self, sql, args=()):
        c = self.connect()
        try:
            return [dict(x) for x in c.execute(sql, args).fetchall()]
        finally:
            c.close()

    def event(self, c, entity, kind, payload):
        c.execute(
            "INSERT INTO events VALUES(?,?,?,?,?)",
            (uid(), entity, kind, dumps(payload), now()),
        )

    def heartbeat(self, name, status):
        with self.tx() as c:
            c.execute(
                "INSERT INTO runtime VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at",
                (name, status, now()),
            )

    def backup(self, target):
        from pathlib import Path

        dest = Path(target).resolve()
        if dest == self.path.resolve() or dest.exists():
            raise ValueError("备份目标必须为不存在的新文件")
        source = self.connect()
        out = sqlite3.connect(dest)
        try:
            source.backup(out)
        finally:
            source.close()
            out.close()
        dest.chmod(0o600)
