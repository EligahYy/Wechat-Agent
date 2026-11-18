"""Archive-backed contact routes; account selection is enforced server-side."""

from contextlib import closing
import sqlite3
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, model_validator

from ..accounts import authorize_account as check_account
from ..profiles.status import ProfileFilter
from ..contacts.service import ContactError, Role, list_contacts, set_roles
from ..source.contracts import ContactKey
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
    check_account(conn, request.app.state.settings, request.app.state.services, account_id)


@router.get("/api/contacts")
def contacts(request: Request, account_id: str = Query(min_length=1, max_length=512),
             q: str = Query(default="", max_length=256),
             role: Literal["all", "merchant", "provider", "platform", "unknown"] = "all",
             scope: Literal["all", "business"] = "all", membership: Literal["all", "included", "excluded"] = "all",
             profile_status: ProfileFilter = "all",
             page: int = Query(default=1, ge=1, le=1000000), page_size: int = Query(default=20, ge=1, le=20)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            authorize_account(request, conn, account_id)
            return list_contacts(conn, account_id, q=q, role=role, page=page, page_size=page_size, scope=scope, membership=membership,
                                 profile_status=profile_status)
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


class ScopeRequestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: ContactKey
    expected_version: StrictInt = Field(ge=0, le=2**63-2)

class ScopeBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str = Field(min_length=1, max_length=512)
    included: StrictBool
    items: list[ScopeRequestItem] = Field(min_length=1, max_length=500)

@router.patch("/api/contacts/scope")
def update_scope(request: Request, batch: ScopeBatch):
    from ..contacts.scope import set_scope
    if any(item.key.account_id != batch.account_id for item in batch.items):
        raise ContactError("account_scope_forbidden",403)
    if len({item.key for item in batch.items}) != len(batch.items):
        raise ContactError("invalid_scope_batch",422)
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_account(request,conn,batch.account_id)
            result=set_scope(conn,[item.key for item in batch.items],batch.included,
                             {item.key.contact_id:item.expected_version for item in batch.items})
    except sqlite3.Error:
        raise ContactError("contact_update_failed",503) from None
    if result.failed:
        return JSONResponse(status_code=409, content={"code":"scope_version_conflict",
            "message":"业务范围修改存在冲突，请核对结果", "details":result.model_dump(mode="json")})
    return result
