"""Account-scoped configuration and explicitly requested connection checks."""
import asyncio
from contextlib import closing
import sqlite3
import time
from uuid import uuid4
from fastapi import APIRouter,Request,Query
from pydantic import BaseModel,ConfigDict,Field,StrictInt
from ..accounts import authorize_account
from ..model.credentials import CredentialStore
from ..model.contracts import ModelCallError
from ..model.settings import ModelSettingsUpdate,read_saved,public_settings,save_settings
from ..model.deepseek import check_connection
from ..operations.service import OperationError
from ..source.repository import transaction
from ..storage.db import open_existing_db

router=APIRouter()
class CheckRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_id:str=Field(min_length=1,max_length=512)
    expected_version:StrictInt=Field(ge=0)

def store(request):return request.app.state.services.credential_store or CredentialStore()
def authorize(conn,request,account):authorize_account(conn,request.app.state.settings,request.app.state.services,account)

@router.get('/api/model')
def get_model(request:Request,account_id:str=Query(min_length=1,max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize(conn,request,account_id)
            return public_settings(conn,account_id)
    except sqlite3.Error:raise OperationError('database_unavailable',503) from None

@router.put('/api/model')
def put_model(request:Request,body:ModelSettingsUpdate):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize(conn,request,body.account_id)
            return save_settings(conn,body,store(request))
    except ModelCallError as error:raise OperationError(error.code,503) from None
    except sqlite3.Error:raise OperationError('model_settings_write_failed',503) from None

@router.post('/api/model/check')
def check_model(request:Request,body:CheckRequest):
    identifier=str(uuid4());now=time.time()
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize(conn,request,body.account_id)
            with transaction(conn):
                saved,version=read_saved(conn,body.account_id)
                if saved is None or version!=body.expected_version:raise OperationError('model_version_conflict',409)
                conn.execute("UPDATE model_connection_checks SET state='interrupted',code='check_interrupted' WHERE account_id=? AND state='running' AND expires_at<=?",(body.account_id,now))
                if conn.execute("SELECT 1 FROM model_connection_checks WHERE account_id=? AND state='running'",(body.account_id,)).fetchone():raise OperationError('model_check_running',409)
                conn.execute("INSERT INTO model_connection_checks(account_id,check_id,config_version,state,started_at,expires_at) VALUES(?,?,?,'running',?,?)",(body.account_id,identifier,version,now,now+330))
            try:state,code=asyncio.run(check_connection(saved,store(request),request.app.state.services.model_transport))
            except ModelCallError as error:state,code='failed',error.code
            with transaction(conn):
                _,current=read_saved(conn,body.account_id)
                conn.execute("UPDATE model_connection_checks SET state=?,code=?,finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE account_id=? AND check_id=?",(state if current==version else 'superseded',code,body.account_id,identifier))
            if current!=version:raise OperationError('model_check_stale',409)
            return public_settings(conn,body.account_id)
    except sqlite3.Error:raise OperationError('model_check_failed',503) from None


from ..model.budget import BudgetReview,review_budget

@router.post('/api/model/budget-review')
def confirm_budget(request:Request,body:BudgetReview):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize(conn,request,body.account_id)
            return review_budget(conn,body)
    except sqlite3.Error:raise OperationError('model_settings_write_failed',503) from None
