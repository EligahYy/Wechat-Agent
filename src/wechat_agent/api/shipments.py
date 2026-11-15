"""Human numbers editing scoped to both account and customer."""
from contextlib import closing
import sqlite3
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,Field,StrictInt,StrictStr
from .archive_access import authorize_archive
from ..profiles.manual import save_numbers,MAX_VERSION,contact_key
from ..operations.service import OperationError
from ..storage.db import open_existing_db

router=APIRouter()
class NumbersUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_id:str=Field(min_length=1,max_length=512)
    contact_id:str=Field(min_length=1,max_length=512)
    numbers:list[StrictStr]=Field(max_length=100)
    expected_version:StrictInt=Field(ge=1,le=MAX_VERSION)


@router.patch('/api/shipments/{shipment_id}/numbers')
def update_numbers(request:Request,shipment_id:str,body:NumbersUpdate):
    try:
        with closing(open_existing_db(request.app.state.database_path)) as conn:
            authorize_archive(conn,request,body.account_id)
            return save_numbers(conn,contact_key(body.account_id,body.contact_id),shipment_id,body.numbers,body.expected_version)
    except sqlite3.Error:raise OperationError('shipment_write_failed',503) from None
