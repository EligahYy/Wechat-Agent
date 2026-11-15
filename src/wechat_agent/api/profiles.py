"""Account-authorized profile composition and human override writes."""
from contextlib import closing
import sqlite3
from fastapi import APIRouter,Query,Request
from pydantic import Field,StrictInt
from .archive_access import authorize_archive
from ..profiles.manual import ManualPatch,read_profile,save_manual,MAX_VERSION,contact_key
from ..storage.db import open_existing_db
from ..operations.service import OperationError

router=APIRouter()

class ManualUpdate(ManualPatch):
    account_id:str=Field(min_length=1,max_length=512)
    expected_version:StrictInt=Field(ge=0,le=MAX_VERSION)


@router.get('/api/contacts/{contact_id}/profile')
def get_profile(request:Request,contact_id:str,account_id:str=Query(min_length=1,max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            return read_profile(conn,contact_key(account_id,contact_id))
    except sqlite3.Error:raise OperationError('database_unavailable',503) from None


@router.patch('/api/contacts/{contact_id}/manual')
def update_manual(request:Request,contact_id:str,body:ManualUpdate):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_archive(conn,request,body.account_id)
            version=save_manual(conn,contact_key(body.account_id,contact_id),body.model_dump(exclude={'account_id','expected_version'}),body.expected_version)
            return {'account_id':body.account_id,'contact_id':contact_id,'manual_version':version,'origin':'manual'}
    except sqlite3.Error:raise OperationError('manual_write_failed',503) from None
