"""Fast HTTP intentions; execution runs in the lifespan-owned worker."""

from contextlib import closing
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..operations.contracts import OperationScope, SyncOptions
from ..operations.service import OperationError, control_operation, create_operation, get_operation
from ..storage.db import open_existing_db
from .contacts import authorize_account


router = APIRouter()


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["sync", "sync_and_organize"]
    scope: OperationScope
    idempotency_key: str = Field(min_length=1, max_length=256)
    options: SyncOptions = Field(default_factory=SyncOptions)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["stop"]
    account_id: str = Field(min_length=1, max_length=512)
    operation_id: str = Field(min_length=1, max_length=128)


@router.post("/api/operations")
async def submit(request: Request, body: Annotated[CreateRequest | StopRequest, Body(discriminator="action")]):
    account_id = body.scope.account_id if isinstance(body, CreateRequest) else body.account_id
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_account(request, conn, account_id)
            if isinstance(body, CreateRequest):
                result = create_operation(conn, body.action, body.scope, body.idempotency_key, options=body.options)
            else:
                result = control_operation(conn, account_id, body.operation_id, "stop")
    except sqlite3.Error:
        raise OperationError("operation_write_failed", 503) from None
    runtime = request.app.state.worker
    if runtime:
        if isinstance(body, StopRequest):
            runtime.stop_operation(result.id)
        else:
            runtime.wake.set()
    return JSONResponse(status_code=202 if isinstance(body, CreateRequest) else 200, content=result.model_dump(mode="json"))


@router.get("/api/operations")
def history(request: Request, account_id: str = Query(min_length=1, max_length=512),
            page: int = Query(default=1, ge=1, le=1000000), page_size: int = Query(default=20, ge=1, le=20)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            authorize_account(request, conn, account_id)
            total = conn.execute("SELECT COUNT(*) FROM operations WHERE account_id=?", (account_id,)).fetchone()[0]
            ids = conn.execute("SELECT id FROM operations WHERE account_id=? ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?",
                               (account_id, page_size, (page - 1) * page_size)).fetchall()
            items = [get_operation(conn, account_id, row[0], include_items=False).model_dump(mode="json", exclude={"items"}) for row in ids]
    except sqlite3.Error:
        raise OperationError("database_unavailable", 503) from None
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/api/operations/{operation_id}")
def detail(request: Request, operation_id: str, account_id: str = Query(min_length=1, max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            authorize_account(request, conn, account_id)
            return get_operation(conn, account_id, operation_id)
    except sqlite3.Error:
        raise OperationError("database_unavailable", 503) from None
