"""Settings-only import endpoint with bounded JSON bodies and explicit preview IDs."""
from contextlib import closing
import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from .archive_access import authorize_archive
from ..operations.service import OperationError
from ..source.adapter import SourceError
from ..source import imports as service
from ..storage.db import open_existing_db

router=APIRouter()

class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['preview']
    account_id:str=Field(min_length=1,max_length=512)
    format:Literal['csv','json']
    namespace:str=Field(min_length=1,max_length=128)
    content:str
    mapping:dict[str,str]|None=None

    @field_validator('namespace')
    @classmethod
    def valid_namespace(cls,value):
        if not value.strip() or any(not char.isprintable() for char in value):raise ValueError('namespace_invalid')
        return value.strip()

    @field_validator('mapping')
    @classmethod
    def valid_mapping(cls,value):
        if value is not None and (set(value)-set((*service.REQUIRED,*service.OPTIONAL)) or any(len(v)>256 for v in value.values())):
            raise ValueError('mapping_invalid')
        return value

class Commit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['commit']
    account_id:str=Field(min_length=1,max_length=512)
    preview_id:str=Field(min_length=1,max_length=64)

REQUEST=TypeAdapter(Annotated[Preview|Commit,Field(discriminator='mode')])


def _execute(request,body):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_archive(conn,request,body.account_id)
            if isinstance(body,Commit):return service.commit(conn,body.account_id,body.preview_id)
            return service.preview(conn,body.account_id,body.namespace,body.format,body.content,body.mapping)
    except (sqlite3.Error,SourceError):
        raise OperationError('import_write_failed',503) from None


@router.post('/api/imports')
async def import_messages(request:Request):
    if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
        raise OperationError('import_content_type_required',415)
    payload=bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload)>service.MAX_CONTENT*3+65536:
            raise OperationError('import_too_large',413)
    try:
        decoded=json.loads(bytes(payload),parse_constant=service._reject_constant)
        json.dumps(decoded,ensure_ascii=False,allow_nan=False).encode('utf-8')
        body=REQUEST.validate_python(decoded)
    except (ValueError,UnicodeError,ValidationError,RecursionError):
        raise OperationError('import_request_invalid',422) from None
    return await run_in_threadpool(_execute,request,body)
