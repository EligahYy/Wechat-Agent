"""Archive-backed contact routes; account selection is enforced server-side."""

from contextlib import closing
import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..contacts.service import ContactError, Role, list_contacts, set_roles
from ..source.contracts import ContactKey
from ..source.probe import SourceConfig
from ..storage.db import open_existing_db


router = APIRouter()


class RoleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ContactKey
    expected_version: StrictInt = Field(ge=1, le=2**63 - 1)


class RoleBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=512)
    role: Role
    items: list[RoleItem] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.key for item in self.items}) != len(self.items):
            raise ValueError("duplicate_contacts")
        return self


def authorize_account(request, conn, account_id):
    binding = None
    config = request.app.state.settings.source_config
    if config:
        try:
            binding = SourceConfig.model_validate(json.loads(config.read_text())).expected_account_id
        except (OSError, ValueError, TypeError):
            raise ContactError("account_configuration_invalid", 503) from None
    source = request.app.state.services.source
    if source is not None:
        if binding and binding != source.account_id:
            raise ContactError("account_configuration_mismatch", 503)
        binding = source.account_id
    if binding is None:
        accounts = conn.execute("SELECT account_id FROM accounts ORDER BY account_id LIMIT 2").fetchall()
        if len(accounts) != 1:
            raise ContactError("account_binding_required")
        binding = accounts[0][0]
    if account_id != binding:
        raise ContactError("account_scope_forbidden", 403)


@router.get("/api/contacts")
def contacts(request: Request, account_id: str = Query(min_length=1, max_length=512),
             q: str = Query(default="", max_length=256),
             role: Literal["all", "merchant", "provider", "platform", "unknown"] = "all",
             page: int = Query(default=1, ge=1, le=1000000), page_size: int = Query(default=20, ge=1, le=20)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            authorize_account(request, conn, account_id)
            return list_contacts(conn, account_id, q=q, role=role, page=page, page_size=page_size)
    except sqlite3.Error:
        raise ContactError("database_unavailable", 503) from None


@router.patch("/api/contacts/roles")
def update_roles(request: Request, batch: RoleBatch):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_account(request, conn, batch.account_id)
            if any(item.key.account_id != batch.account_id for item in batch.items):
                raise ContactError("account_scope_forbidden", 403)
            result = set_roles(conn, [item.key for item in batch.items], batch.role,
                               {item.key.contact_id: item.expected_version for item in batch.items})
    except sqlite3.Error:
        raise ContactError("contact_update_failed", 503) from None
    if result.failed:
        code = ("role_version_conflict" if any(item.code == "role_version_conflict" for item in result.failed)
                else "role_update_conflict")
        return JSONResponse(status_code=409, content={
            "code": code, "message": "身份修改存在冲突，请核对结果", "details": result.model_dump(mode="json")})
    return result
