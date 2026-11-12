"""Attachment ID access never accepts a user-provided disk path."""
from contextlib import closing
import re
import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from .archive_access import authorize_archive
from ..attachments.access import open_attachment
from ..operations.service import OperationError
from ..storage.db import open_existing_db

router=APIRouter()


@router.get('/api/attachments/{attachment_id}')
def attachment(request:Request,attachment_id:str,account_id:str=Query(min_length=1,max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            row=conn.execute('SELECT * FROM attachments WHERE account_id=? AND attachment_id=?',(account_id,attachment_id)).fetchone()
            if row is None:raise OperationError('attachment_not_found',404)
            if row['state'] not in ('original','thumbnail') or not row['local_path']:
                raise OperationError('attachment_not_available',409,{'state':row['state']})
            path,mime=row['local_path'],row['mime']
    except sqlite3.Error:
        raise OperationError('database_unavailable',503) from None
    try:handle,size,filename=open_attachment(request.app.state.settings.data_dir,path)
    except FileNotFoundError:
        raise OperationError('attachment_not_available',409,{'state':'missing'}) from None
    def content():
        try:
            while chunk:=handle.read(65536):yield chunk
        finally:handle.close()
    mime=mime if isinstance(mime,str) and re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+',mime) else 'application/octet-stream'
    filename=''.join(char for char in filename if char.isprintable())[:120] or 'attachment'
    return StreamingResponse(content(),media_type=mime,background=BackgroundTask(handle.close),headers={
        'Content-Length':str(size),'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe=''),
        'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})
