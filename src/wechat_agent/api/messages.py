"""Read-only contact timelines with scoped, revision-bound keyset pagination."""
import base64
from contextlib import closing
import json
import hashlib
import math
import sqlite3

from fastapi import APIRouter, Query, Request

from .archive_access import authorize_archive
from ..contacts.names import load_catalog, present_source_title, resolve_name
from ..operations.service import OperationError
from ..storage.db import open_existing_db

router=APIRouter()
ORDER='COALESCE(julianday(m.sent_at),0)'


def _cursor(value,scope,marker):
    try:
        data=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
        if not isinstance(data,dict) or set(data)!={'scope','marker','last'} or data['scope']!=scope:
            raise ValueError()
        last=data['last']
        if (not isinstance(last,list) or len(last)!=2 or type(last[0]) not in (int,float)
                or not math.isfinite(last[0]) or not isinstance(last[1],str) or len(last[1])>2048
                or not isinstance(data['marker'],str) or len(data['marker'])!=64):
            raise ValueError()
    except (ValueError,TypeError,UnicodeError):
        raise OperationError('message_cursor_invalid',422) from None
    if data['marker']!=marker:
        raise OperationError('message_cursor_stale',409)
    return last


def read_timeline(conn,account_id,contact_id,*,q='',conversation_id=None,page_size=50,cursor=None):
    contact=conn.execute("SELECT * FROM contacts WHERE account_id=? AND contact_id=? AND is_self=0 AND identity_state='active'",(account_id,contact_id)).fetchone()
    if contact is None:
        raise OperationError('messages_not_found',404)
    sources=[dict(row) for row in conn.execute('''SELECT v.conversation_id,v.kind,v.title FROM conversations v
        WHERE v.account_id=? AND (v.conversation_id IN (
            SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?) OR v.conversation_id IN (
            SELECT conversation_id FROM messages WHERE account_id=? AND sender_id=?)) ORDER BY v.kind,v.conversation_id''',
        (account_id,account_id,contact_id,account_id,contact_id))]
    for source in sources:
        source['title']=present_source_title(source['title'],source['conversation_id'])
    if conversation_id is not None and conversation_id not in {source['conversation_id'] for source in sources}:
        raise OperationError('messages_not_found',404)
    q=q.strip()
    scope=[account_id,contact_id,q,conversation_id,page_size]
    revision=conn.execute('SELECT COALESCE(MAX(rowid),0) FROM message_revisions WHERE account_id=?',(account_id,)).fetchone()[0]
    marker=hashlib.sha256(json.dumps([revision,[source['conversation_id'] for source in sources]],ensure_ascii=False).encode()).hexdigest()
    last=_cursor(cursor,scope,marker) if cursor else None
    clauses=['''m.account_id=? AND m.kind NOT IN ('system','revoke') AND (m.sender_id=? OR m.conversation_id IN (
        SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?))''']
    params=[account_id,contact_id,account_id,contact_id]
    if conversation_id is not None:
        clauses.append('m.conversation_id=?');params.append(conversation_id)
    if q:
        if len(q)>=3 and any(char.isalnum() for char in q):
            clauses.append('m.rowid IN (SELECT rowid FROM message_search WHERE message_search MATCH ?)')
            params.append('"'+q.replace('"','""')+'"')
        else:
            clauses.append("m.body LIKE ? ESCAPE '\\'")
            params.append('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    where=' AND '.join(clauses)
    total=conn.execute('SELECT COUNT(*) FROM messages m WHERE '+where,params).fetchone()[0]
    if last:
        where+=f' AND ({ORDER}>? OR ({ORDER}=? AND m.message_id>?))'
        params.extend([last[0],last[0],last[1]])
    rows=conn.execute(f'''SELECT m.*,{ORDER} AS order_time,v.title AS source_title,v.kind AS source_kind
        FROM messages m JOIN conversations v ON v.account_id=m.account_id AND v.conversation_id=m.conversation_id
        WHERE {where} ORDER BY order_time,m.message_id LIMIT ?''',[*params,page_size+1]).fetchall()
    more=len(rows)>page_size;rows=rows[:page_size]
    senders={row['sender_id'] for row in rows if row['sender_id'] is not None}
    people={}
    if senders:
        placeholders=','.join('?' for _ in senders)
        people={row['contact_id']:row for row in conn.execute(f'SELECT * FROM contacts WHERE account_id=? AND contact_id IN ({placeholders})',[account_id,*senders])}
    catalog=load_catalog(conn,account_id,contact_ids=senders)
    source_map={source['conversation_id']:source for source in sources}
    items=[]
    for row in rows:
        person=people.get(row['sender_id'])
        if row['sender_id'] is None:
            sender={'contact_id':None,'display_name':'系统消息','role':None,'is_self':False,'identity_state':'unassigned'}
        elif person is None or person['identity_state']!='active':
            sender={'contact_id':None,'display_name':'归属待核实','role':None,'is_self':False,'identity_state':'quarantined'}
        else:
            is_self=bool(person['is_self']) or row['sender_id']==account_id
            name=resolve_name(person,catalog[row['sender_id']])
            sender={'contact_id':row['sender_id'],'display_name':'我方' if is_self else name['display_name'],
                    'role':None if is_self else person['role'],'is_self':is_self,'identity_state':'active','name_status':name['name_status']}
        attachments=[{'id':a['attachment_id'],'state':a['state'],'mime':a['mime'],'reason':a['reason'],
                      'downloadable':a['state'] in ('original','thumbnail') and bool(a['local_path'])}
            for a in conn.execute('SELECT * FROM attachments WHERE account_id=? AND message_id=? ORDER BY attachment_id',(account_id,row['message_id']))]
        source=source_map[row['conversation_id']]
        items.append({'message_id':row['message_id'],'conversation_id':row['conversation_id'],'source_title':source['title'],
            'source_kind':source['kind'],'sender':sender,'sent_at':row['sent_at'],'kind':row['kind'],
            'body':row['body'],'revision':row['revision'],'reply_to':row['reply_to'],'attachments':attachments,
            'origin':'import' if row['message_id'].startswith('import:') else 'archive'})
    next_cursor=None
    if more:
        tail=rows[-1]
        next_cursor=base64.urlsafe_b64encode(json.dumps({'scope':scope,'marker':marker,'last':[tail['order_time'],tail['message_id']]}).encode()).decode().rstrip('=')
    return {'items':items,'total':total,'sources':sources,'next_cursor':next_cursor,'has_more':more,'timezone':'Asia/Shanghai'}


@router.get('/api/contacts/{contact_id}/messages')
def messages(request:Request,contact_id:str,account_id:str=Query(min_length=1,max_length=512),q:str=Query(default='',max_length=256),
             conversation_id:str|None=Query(default=None,min_length=1,max_length=512),page_size:int=Query(default=50,ge=1,le=50),
             cursor:str|None=Query(default=None,max_length=4096)):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            return read_timeline(conn,account_id,contact_id,q=q,conversation_id=conversation_id,page_size=page_size,cursor=cursor)
    except sqlite3.Error:
        raise OperationError('database_unavailable',503) from None
