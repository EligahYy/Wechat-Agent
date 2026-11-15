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
from ..messages.presentation import display_body
from ..messages.queries import timeline_sources,message_scope
from ..messages.calendar import day_bounds,read_calendar

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


def read_timeline(conn,account_id,contact_id,*,q='',conversation_id=None,page_size=50,cursor=None,before_cursor=None,focus_id=None,focus_latest=False,day=None,date_latest=False):
    sources=timeline_sources(conn,account_id,contact_id,conversation_id)
    q=q.strip()
    scope=[account_id,contact_id,q,conversation_id,page_size]+([day] if day else [])
    revision=conn.execute('SELECT COALESCE(MAX(rowid),0) FROM message_revisions WHERE account_id=?',(account_id,)).fetchone()[0]
    marker=hashlib.sha256(json.dumps([revision,[source['conversation_id'] for source in sources]],ensure_ascii=False).encode()).hexdigest()
    if sum(bool(value) for value in (cursor,before_cursor,focus_id,focus_latest,date_latest))>1:raise OperationError('message_navigation_invalid',422)
    last=_cursor(cursor,scope,marker) if cursor else _cursor(before_cursor,[*scope,'before'],marker) if before_cursor else None
    scope_where,params=message_scope(account_id,contact_id)
    clauses=[scope_where]
    if conversation_id is not None:
        clauses.append('m.conversation_id=?');params.append(conversation_id)
    if day:
        start,end=day_bounds(day)
        clauses.append("julianday(m.sent_at)>=julianday(?) AND julianday(m.sent_at)<julianday(?)");params.extend([start,end])
    if q:
        if len(q)>=3 and any(char.isalnum() for char in q):
            clauses.append('m.rowid IN (SELECT rowid FROM message_search WHERE message_search MATCH ?)')
            params.append('"'+q.replace('"','""')+'"')
        else:
            clauses.append("m.body LIKE ? ESCAPE '\\'")
            params.append('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
    where=' AND '.join(clauses)
    total=conn.execute('SELECT COUNT(*) FROM messages m WHERE '+where,params).fetchone()[0]
    base_where=where;base_params=list(params)
    def encode(row,before=False):
        return base64.urlsafe_b64encode(json.dumps({'scope':[*scope,'before'] if before else scope,'marker':marker,'last':[row['order_time'],row['message_id']]}).encode()).decode().rstrip('=')
    def select(extra='',values=(),descending=False,limit=page_size):
        direction='DESC' if descending else 'ASC'
        return conn.execute(f"SELECT m.*,{ORDER} AS order_time,v.title AS source_title,v.kind AS source_kind FROM messages m JOIN conversations v ON v.account_id=m.account_id AND v.conversation_id=m.conversation_id WHERE {base_where} {extra} ORDER BY order_time {direction},m.message_id {direction} LIMIT ?",[*base_params,*values,limit]).fetchall()
    def boundary(row,operator):
        return f" AND ({ORDER}{operator}? OR ({ORDER}=? AND m.message_id{operator}?))",[row['order_time'],row['order_time'],row['message_id']]
    target=None
    if focus_id or focus_latest or date_latest:
        candidates=select(('' if date_latest else ' AND m.sender_id=?')+(' AND m.message_id=?' if focus_id else ''),([] if date_latest else [contact_id])+([focus_id] if focus_id else []),descending=True,limit=1)
        if focus_id and not candidates:raise OperationError('message_focus_not_found',404)
        target=candidates[0] if candidates else None
    if target:
        extra,values=boundary(target,'<');before=select(extra,values,descending=True,limit=page_size//2)
        extra,values=boundary(target,'>');after=select(extra,values,limit=page_size-len(before)-1)
        rows=[*reversed(before),target,*after]
    elif last:
        extra=f" AND ({ORDER}{'<' if before_cursor else '>'}? OR ({ORDER}=? AND m.message_id{'<' if before_cursor else '>'}?))"
        rows=select(extra,[last[0],last[0],last[1]],descending=bool(before_cursor))
        if before_cursor:rows=list(reversed(rows))
    else:rows=select()
    next_cursor=previous_cursor=None
    if rows:
        extra,values=boundary(rows[-1],'>')
        if select(extra,values,limit=1):next_cursor=encode(rows[-1])
        extra,values=boundary(rows[0],'<')
        if select(extra,values,limit=1):previous_cursor=encode(rows[0],True)
    own_where=base_where+' AND m.sender_id=?';own_params=[*base_params,contact_id]
    own_total=conn.execute('SELECT COUNT(*) FROM messages m WHERE '+own_where,own_params).fetchone()[0]
    if target is not None and target['sender_id']!=contact_id:target=None
    if target is None:target=next((row for row in (reversed(rows) if date_latest else rows) if row['sender_id']==contact_id),None)
    speech={'total':own_total,'current_id':None,'index':0,'previous_id':None,'next_id':None}
    if target:
        extra,values=boundary(target,'<')
        speech.update(current_id=target['message_id'],index=1+conn.execute('SELECT COUNT(*) FROM messages m WHERE '+own_where+extra,[*own_params,*values]).fetchone()[0])
        for name,operator,desc in [('previous_id','<',True),('next_id','>',False)]:
            extra,values=boundary(target,operator);neighbor=select(' AND m.sender_id=?'+extra,[contact_id,*values],descending=desc,limit=1)
            speech[name]=neighbor[0]['message_id'] if neighbor else None
    if target is None and own_total:
        first=select(' AND m.sender_id=?',[contact_id],descending=date_latest,limit=1)
        if first:speech['previous_id' if date_latest else 'next_id']=first[0]['message_id']
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
            'body':display_body(row['kind'],row['body']),'revision':row['revision'],'reply_to':row['reply_to'],'attachments':attachments,
            'origin':'import' if row['message_id'].startswith('import:') else 'archive'})
    return {'items':items,'total':total,'sources':sources,'next_cursor':next_cursor,'previous_cursor':previous_cursor,'speech':speech,'has_more':bool(next_cursor),'timezone':'Asia/Shanghai'}



@router.get('/api/contacts/{contact_id}/messages')
def messages(request:Request,contact_id:str,account_id:str=Query(min_length=1,max_length=512),q:str=Query(default='',max_length=256),
             conversation_id:str|None=Query(default=None,min_length=1,max_length=512),page_size:int=Query(default=50,ge=1,le=50),
             cursor:str|None=Query(default=None,max_length=4096),before_cursor:str|None=Query(default=None,max_length=4096),
             focus_id:str|None=Query(default=None,max_length=2048),focus_latest:bool=False,day:str|None=Query(default=None,max_length=10),date_latest:bool=False):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            return read_timeline(conn,account_id,contact_id,q=q,conversation_id=conversation_id,page_size=page_size,cursor=cursor,before_cursor=before_cursor,focus_id=focus_id,focus_latest=focus_latest,day=day,date_latest=date_latest)
    except sqlite3.Error:
        raise OperationError('database_unavailable',503) from None

@router.get('/api/contacts/{contact_id}/message-calendar')
def calendar(request:Request,contact_id:str,account_id:str=Query(min_length=1,max_length=512),month:str=Query(pattern=r'^\d{4}-\d{2}$'),conversation_id:str|None=Query(default=None,min_length=1,max_length=512)):
    try:
        with closing(open_existing_db(request.app.state.database_path,readonly=True)) as conn,conn:
            conn.execute('BEGIN');authorize_archive(conn,request,account_id)
            return read_calendar(conn,account_id,contact_id,month,conversation_id=conversation_id)
    except sqlite3.Error:raise OperationError('database_unavailable',503) from None
