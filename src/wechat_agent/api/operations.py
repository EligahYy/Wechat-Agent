from ..operations.service import OPERATION_QUERY
"""Fast HTTP intentions; execution runs in the lifespan-owned worker."""

from contextlib import closing
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..operations.contracts import OperationScope, SyncOptions
from ..operations.service import OperationError, control_operation, create_operation, get_operation, resume_operation
from ..storage.db import open_existing_db
from .contacts import authorize_account


router = APIRouter()


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["sync", "sync_and_organize", 'refresh_contacts']
    scope: OperationScope
    idempotency_key: str = Field(min_length=1, max_length=256)
    options: SyncOptions = Field(default_factory=SyncOptions)


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["stop"]
    account_id: str = Field(min_length=1, max_length=512)
    operation_id: str = Field(min_length=1, max_length=128)


class ResumeRequest(StopRequest):
    action: Literal["resume"]


@router.post("/api/operations")
async def submit(request: Request, body: Annotated[CreateRequest | StopRequest | ResumeRequest, Body(discriminator="action")]):
    account_id = body.scope.account_id if isinstance(body, CreateRequest) else body.account_id
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_account(request, conn, account_id)
            if isinstance(body, CreateRequest):
                result = create_operation(conn, body.action, body.scope, body.idempotency_key, options=body.options)
            elif isinstance(body, ResumeRequest):
                result = resume_operation(conn, account_id, body.operation_id)
            else:
                result = control_operation(conn, account_id, body.operation_id, "stop")
    except sqlite3.Error:
        raise OperationError("operation_write_failed", 503) from None
    runtime = request.app.state.worker
    if runtime:
        if body.action == "stop":
            runtime.stop_operation(result.id)
        else:
            runtime.wake.set()
    return JSONResponse(status_code=200 if body.action == "stop" else 202, content=result.model_dump(mode="json"))


@router.get("/api/operations")
def history(request: Request, account_id: str = Query(min_length=1, max_length=512),
            page: int = Query(default=1, ge=1, le=1000000), page_size: int = Query(default=20, ge=1, le=20)):
    try:
        with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
            conn.execute("BEGIN")
            authorize_account(request, conn, account_id)
            total = conn.execute("SELECT COUNT(*) FROM operations WHERE account_id=?", (account_id,)).fetchone()[0]
            ids = conn.execute(OPERATION_QUERY+" WHERE o.account_id=? ORDER BY o.created_at DESC,o.rowid DESC LIMIT ? OFFSET ?",
                               (account_id, page_size, (page - 1) * page_size)).fetchall()
            items = [get_operation(conn, account_id, row["id"], include_items=False, _row=row).model_dump(mode="json", exclude={"items"}) for row in ids]
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


@router.get("/api/operations/{operation_id}/relevance")
def relevance_detail(request: Request, operation_id: str, account_id: str = Query(min_length=1, max_length=512),
                     level: Literal['high', 'medium', 'low'] | None = None,
                     day: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$'),
                     conversation_id: str | None = Query(default=None, max_length=512),
                     page: int = Query(default=1, ge=1)):
    from datetime import datetime
    import json
    from zoneinfo import ZoneInfo

    from ..contacts.scope import business_scope_allows_analysis
    from ..source.contracts import ContactKey
    from ..context.relevance import RelevanceManifest

    with closing(open_existing_db(request.app.state.database_path, readonly=True)) as conn, conn:
        conn.execute('BEGIN')
        authorize_account(request, conn, account_id)
        row = conn.execute(
            """SELECT r.contact_id,r.manifest_json,s.payload_json FROM message_relevance r JOIN snapshots s
                 ON s.account_id=r.account_id AND s.snapshot_id=r.snapshot_id
                 JOIN contacts c ON c.account_id=r.account_id AND c.contact_id=r.contact_id
               WHERE r.account_id=? AND r.operation_id=? AND c.role='merchant' AND c.identity_state='active'""",
            (account_id, operation_id),
        ).fetchone()
        if row is None or not business_scope_allows_analysis(conn, ContactKey(account_id=account_id, contact_id=row[0])):
            raise OperationError('relevance_not_found', 404)
        manifest = RelevanceManifest.model_validate_json(row[1])
        payload = json.loads(row[2])
        messages = {item['message_id']: item for item in payload['messages']}
        items = []
        for entry in manifest.entries:
            if level and level != entry.level:
                continue
            message = messages[entry.message_id]
            room = message['conversation_id']
            if conversation_id and room != conversation_id:
                continue
            stamp = datetime.fromisoformat(message['sent_at'].replace('Z', '+00:00'))
            day_key = stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
            if day and day != day_key:
                continue
            items.append({
                **entry.model_dump(mode='json'), 'day': day_key, 'conversation_id': room,
                'preview': message['body'][:160],
            })
        return {'items': items[(page - 1) * 20:page * 20], 'total': len(items), 'page': page,
                'rule_version': manifest.rule_version, 'sources': payload['conversations']}
