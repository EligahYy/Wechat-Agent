"""Account-scoped non-secret UI preferences; no capability probe on page load."""

from contextlib import closing
import json
import re
import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

from ..accounts import AccountError, authorize_account, selected_account
from ..operations.service import OperationError
from ..source.repository import transaction
from ..storage.db import open_existing_db

router = APIRouter()


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_time: str = "08:30"
    daily_enabled: StrictBool = False
    appearance: Literal["system", "light", "dark"] = "system"
    reduce_motion: StrictBool = False

    @field_validator("daily_time")
    @classmethod
    def valid_time(cls, value):
        if not re.fullmatch(r"(?:[01]?\d|2[0-3]):[0-5]\d", value, re.ASCII):
            raise ValueError("invalid_schedule_time")
        return value.zfill(5)


class PreferenceChanges(Preferences):
    # Only explicitly supplied fields are merged into the existing preferences.
    pass


class UpdateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=512)
    expected_version: StrictInt = Field(ge=0, le=2**63-2)
    preferences: PreferenceChanges


def _read(conn, account_id):
    row = conn.execute("SELECT value_json,version FROM settings WHERE account_id=? AND name='preferences'", (account_id,)).fetchone()
    try:
        return (Preferences.model_validate_json(row[0]), row[1]) if row else (Preferences(), 0)
    except ValueError:
        raise OperationError("settings_invalid", 503) from None


def _response(conn, request, account_id):
    preferences, version = _read(conn, account_id)
    model = {"state": "unconfigured", "model_id": None}
    path = request.app.state.settings.model_config
    if path:
        try:
            identifier = json.loads(path.read_text()).get("model_id")
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier)>256:
                raise ValueError()
            model = {"state": "configured", "model_id": identifier}
        except (OSError, ValueError, AttributeError):
            model["state"] = "invalid"
    from ..model.settings import public_settings
    stored_model=public_settings(conn,account_id)
    if stored_model['configured']:
        model={'state':'configured','model_id':stored_model['model_id'],'connection_state':stored_model['connection']['state'],'runtime_ready':stored_model['runtime_ready']}
    previous = conn.execute("""SELECT i.state,o.updated_at,o.action FROM operations o JOIN operation_items i
        ON i.account_id=o.account_id AND i.operation_id=o.id AND i.item_id='source'
        WHERE o.account_id=? ORDER BY o.created_at DESC,o.rowid DESC LIMIT 1""", (account_id,)).fetchone()
    source = {"state": "not_checked", "last_sync_at": None}
    if previous:
        metadata_only = previous[2] == 'refresh_contacts'
        source['state'] = ('last_metadata_' if metadata_only else 'last_sync_') + previous[0]
        if metadata_only:
            source['last_metadata_at'] = previous[1]
            last_sync = conn.execute("""SELECT updated_at FROM operations
                WHERE account_id=? AND action!='refresh_contacts'
                ORDER BY created_at DESC,rowid DESC LIMIT 1""", (account_id,)).fetchone()
            source['last_sync_at'] = last_sync[0] if last_sync else None
        else:
            source['last_sync_at'] = previous[1]
    return {"account_id": account_id, "preferences": preferences.model_dump(), "version": version,
        "timezone": "Asia/Shanghai", "source": source, "model": model,
        "capabilities": {"organize": bool(stored_model.get("runtime_ready")), "scheduler": False, "raw_browser": True}}


@router.get("/api/settings")
def read_settings(request: Request, account_id: str | None = Query(default=None, min_length=1, max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            if account_id:
                authorize_account(conn, request.app.state.settings, request.app.state.services, account_id)
            else:
                try:
                    account_id = selected_account(conn, request.app.state.settings, request.app.state.services)
                except AccountError as error:
                    if error.code != "account_binding_required" or conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]:
                        raise
            return _response(conn, request, account_id)
    except sqlite3.Error:
        raise OperationError("database_unavailable", 503) from None


@router.patch("/api/settings")
def update_settings(request: Request, body: UpdateSettings):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_account(conn, request.app.state.settings, request.app.state.services, body.account_id)
            with transaction(conn):
                preferences, version = _read(conn, body.account_id)
                if version != body.expected_version:
                    raise OperationError("settings_version_conflict", details={"version": version})
                saved = Preferences.model_validate({**preferences.model_dump(), **body.preferences.model_dump(exclude_unset=True)})
                conn.execute("INSERT INTO accounts(account_id) VALUES (?) ON CONFLICT DO NOTHING", (body.account_id,))
                conn.execute("""INSERT INTO settings(account_id,name,value_json,version) VALUES (?,'preferences',?,?)
                    ON CONFLICT(account_id,name) DO UPDATE SET value_json=excluded.value_json,version=excluded.version""",
                    (body.account_id, saved.model_dump_json(), version+1))
            return _response(conn, request, body.account_id)
    except sqlite3.Error:
        raise OperationError("settings_write_failed", 503) from None
