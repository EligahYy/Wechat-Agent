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


@router.get('/api/contacts/{contact_id}/profile/evidence')
def get_evidence(request:Request,contact_id:str,account_id:str=Query(min_length=1,max_length=512),message_id:str=Query(min_length=1,max_length=512),revision:int=Query(gt=0)):
    import json
    from ..profiles.manual import _contact
    from ..messages.presentation import display_body
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            key=contact_key(account_id,contact_id);_contact(conn,key)
            row=conn.execute('''SELECT v.result_json,s.payload_json FROM profile_heads h JOIN profile_versions v
                ON v.account_id=h.account_id AND v.contact_id=h.contact_id AND v.version=h.version
                JOIN snapshots s ON s.account_id=v.account_id AND s.snapshot_id=v.snapshot_id
                WHERE h.account_id=? AND h.contact_id=?''',(account_id,contact_id)).fetchone()
            if not row:raise OperationError('profile_evidence_not_found',404)
            def cited(value):
                if isinstance(value,dict):
                    if value.get('message_id')==message_id and value.get('revision')==revision:return True
                    return any(cited(child) for child in value.values())
                return isinstance(value,list) and any(cited(child) for child in value)
            if not cited(json.loads(row['result_json'])):raise OperationError('profile_evidence_not_found',404)
            payload=json.loads(row['payload_json']);messages=payload['messages']
            target=next((item for item in messages if item['message_id']==message_id and item['revision']==revision),None)
            if not target:raise OperationError('profile_evidence_not_found',404)
            conversation=[item for item in messages if item['conversation_id']==target['conversation_id']]
            index=conversation.index(target);items=[]
            for item in conversation[max(0,index-2):index+3]:
                actor=payload['actors'].get(item['sender_id'],{})
                current=conn.execute('SELECT revision FROM messages WHERE account_id=? AND message_id=?',(account_id,item['message_id'])).fetchone()
                source=payload['conversations'].get(item['conversation_id'],{})
                items.append({**item,'body':display_body(item['kind'],item['body']),'sender_name':actor.get('name') or ('我方' if actor.get('is_self') else '名称缺失'),
                    'source_title':source.get('title') or ('私聊' if source.get('kind')=='private' else '群名称缺失'),
                    'is_evidence':item['message_id']==message_id,'is_historical':not current or current[0]!=item['revision']})
            return {'items':items,'timezone':'Asia/Shanghai'}
    except sqlite3.Error:raise OperationError('database_unavailable',503) from None
