"""Bounded mapped imports, previewed before immutable namespaced records are written."""
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import time
from uuid import uuid4

from pydantic import ValidationError

from ..identities import is_person_identifier
from ..operations.service import OperationError
from .contracts import MessageRecord, SourcePage
from .repository import _account, _archive_page_locked, transaction

MAX_CONTENT=2*1024*1024
MAX_ROWS=5000
REQUIRED=('conversation_id','sender_id','sent_at','message_id','body')
OPTIONAL=('account_id','kind','conversation_kind','attachment_ids')
csv.field_size_limit(MAX_CONTENT)


def _reject_constant(value):
    raise ValueError('invalid_json_constant')


def _error(code,status=422):
    raise OperationError(code,status)


def inspect(content,format):
    try:
        if len(content.encode('utf-8'))>MAX_CONTENT:
            _error('import_too_large',413)
    except UnicodeError:
        _error('import_encoding_invalid')
    if '\x00' in content:
        _error('import_content_invalid')
    try:
        if format=='csv':
            reader=csv.reader(io.StringIO(content.lstrip('\ufeff')),strict=True)
            columns=next(reader)
            if not columns or any(not key.strip() for key in columns) or len(set(columns))!=len(columns):
                _error('import_columns_invalid')
            rows=[]
            for values in reader:
                if not values:continue
                rows.append(dict(zip(columns,values)) if len(values)==len(columns) else None)
                if len(rows)>MAX_ROWS:_error('import_too_many_rows',413)
        else:
            rows=json.loads(content.lstrip('\ufeff'),parse_constant=_reject_constant)
            if not isinstance(rows,list):_error('import_rows_required')
            if len(rows)>MAX_ROWS:_error('import_too_many_rows',413)
            columns=list(dict.fromkeys(key for row in rows if isinstance(row,dict) for key in row))
        if not rows:_error('import_empty')
        if len(columns)>100 or any(not isinstance(key,str) or not key or len(key)>256 for key in columns):
            _error('import_columns_invalid')
        # JSON escapes are decoded only here; validate unused fields and keys too.
        json.dumps(rows,ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (ValueError,UnicodeError,csv.Error,StopIteration,RecursionError):
        _error('import_content_invalid')
    return columns,rows


def _timestamp(value):
    if not isinstance(value,str):raise ValueError('time_invalid')
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.utcoffset() is None:raise ValueError()
        return result.astimezone(timezone.utc)
    except OverflowError:
        raise ValueError('time_invalid') from None
    except ValueError:
        raise ValueError('time_timezone_required') from None


def _identity(namespace,conversation_id,external_id,prefix='import:'):
    value=json.dumps([namespace,conversation_id,external_id],ensure_ascii=False,separators=(',',':'))
    return prefix+hashlib.sha256(value.encode()).hexdigest()


def _record(conn,row,number,account,namespace,mapping):
    if not isinstance(row,dict):raise ValueError('row_not_object')
    if row.get('account_id') not in (None,'',account):raise ValueError('account_scope_mismatch')
    for key in REQUIRED:
        if not mapping.get(key) or mapping[key] not in row:raise ValueError('mapping_required')
    values={key:row.get(column) for key,column in mapping.items() if column}
    if values.get('account_id') not in (None,'',account):raise ValueError('account_scope_mismatch')
    for key in ('conversation_id','message_id'):
        if not isinstance(values[key],str) or not values[key].strip() or len(values[key])>512:
            raise ValueError(key+'_required')
    room=values['conversation_id'].strip();external=values['message_id'].strip()
    if any(not char.isprintable() for char in room):raise ValueError('conversation_id_invalid')
    kind=values.get('kind') or 'text'
    if not isinstance(kind,str) or not kind or len(kind)>32:raise ValueError('kind_invalid')
    sender=values['sender_id']
    if sender in (None,'') and kind in ('system','revoke'):
        sender=None
    elif not is_person_identifier(sender):raise ValueError('sender_id_invalid')
    if not isinstance(values['body'],str) or len(values['body'])>128*1024:raise ValueError('body_invalid')
    stamp=_timestamp(values['sent_at'])
    identifier=_identity(namespace,room,external)
    attachments=values.get('attachment_ids') or []
    if isinstance(attachments,str):
        try:attachments=json.loads(attachments)
        except ValueError:raise ValueError('attachment_references_invalid') from None
    if not isinstance(attachments,list) or len(attachments)>32 or any(not isinstance(a,str) or not a or len(a)>512 for a in attachments):
        raise ValueError('attachment_references_invalid')
    references=sorted({_identity(namespace,identifier,a,'import-att:') for a in attachments})
    existing_room=conn.execute('SELECT kind FROM conversations WHERE account_id=? AND conversation_id=?',(account,room)).fetchone()
    room_kind=values.get('conversation_kind') or (existing_room[0] if existing_room else 'group' if room.endswith('@chatroom') else 'private')
    if room_kind not in ('private','group') or (existing_room and existing_room[0]!=room_kind):
        raise ValueError('conversation_kind_conflict')
    signature=[room,room_kind,sender,stamp.isoformat(),kind,values['body'],references]
    revision=hashlib.sha256(json.dumps(signature,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    record=MessageRecord(account_id=account,conversation_id=room,message_id=identifier,sender_id=sender,
        sent_at=stamp,kind=kind,body=values['body'],attachment_ids=references,source_revision=revision,
        raw={'origin':'manual_import','namespace':namespace,'external_message_id':external,'row':number,'fields':row})
    return {'row':number,'conversation_kind':room_kind,'record':record.model_dump(mode='json')}


def _classification(conn,item):
    record=item['record']
    row=conn.execute('SELECT source_revision FROM messages WHERE account_id=? AND message_id=?',
                     (record['account_id'],record['message_id'])).fetchone()
    if row is None:return 'new'
    return 'unchanged' if row[0]==record['source_revision'] else 'conflict'


def preview(conn,account,namespace,format,content,mapping):
    columns,rows=inspect(content,format)
    samples=[{key:str(value)[:160] for key,value in row.items()} for row in rows[:3] if isinstance(row,dict)]
    result={'columns':columns,'sample_rows':samples,'total_rows':len(rows),'preview_id':None,'issues':[],
            'mapping_defaults':{key:key if key in columns else '' for key in (*REQUIRED,*OPTIONAL)}}
    if mapping is None:return result
    records=[];issues=[];seen={};room_kinds={};duplicates=0;existing=0
    for number,row in enumerate(rows,1):
        try:
            item=_record(conn,row,number,account,namespace,mapping)
            room=item['record']['conversation_id']
            if room in room_kinds and room_kinds[room]!=item['conversation_kind']:
                raise ValueError('conversation_kind_conflict')
            identifier=item['record']['message_id'];revision=item['record']['source_revision']
            if identifier in seen:
                if seen[identifier]['record']['source_revision']!=revision:raise ValueError('duplicate_identity_conflict')
                seen[identifier]['rows'].append(number)
                duplicates+=1;continue
            status=_classification(conn,item)
            if status=='conflict':raise ValueError('message_identity_conflict')
            existing+=status=='unchanged'
            room_kinds[room]=item['conversation_kind']
            item['rows']=[number];seen[identifier]=item
            item['status']=status;records.append(item)
        except (ValueError,ValidationError) as error:
            code=str(error) if type(error) is ValueError else 'message_contract_invalid'
            issues.append({'row':number,'code':code})
    counts={'valid':len(rows)-len(issues),'rejected':len(issues),'new':len(records)-existing,'unchanged':existing+duplicates,'total':len(rows)}
    identifier=str(uuid4());now=int(time.time())
    payload={'records':records,'issues':issues[:100],'rejected':len(issues),'duplicates':duplicates,'total':len(rows)}
    with transaction(conn):
        _account(conn,account)
        conn.execute("DELETE FROM import_previews WHERE account_id=? AND state='ready' AND expires_at<?",(account,now))
        if conn.execute("SELECT COUNT(*) FROM import_previews WHERE account_id=? AND state='ready'",(account,)).fetchone()[0]>=8:
            oldest=conn.execute("SELECT preview_id FROM import_previews WHERE account_id=? AND state='ready' ORDER BY created_at,preview_id LIMIT 1",(account,)).fetchone()[0]
            conn.execute('DELETE FROM import_previews WHERE account_id=? AND preview_id=?',(account,oldest))
        conn.execute('''INSERT INTO import_previews(account_id,preview_id,namespace,state,created_at,expires_at,payload_json)
            VALUES(?,?,?,'ready',?,?,?)''',(account,identifier,namespace,now,now+3600,json.dumps(payload,ensure_ascii=False)))
    return {**result,'preview_id':identifier,'counts':counts,'issues':issues[:100],'issues_truncated':len(issues)>100,
            'sample_messages':[{'row':item['row'],'sender_id':item['record']['sender_id'],
                'conversation_id':item['record']['conversation_id'],'sent_at':item['record']['sent_at'],
                'body':item['record']['body'][:240],'status':item['status']} for item in records[:20]]}


def commit(conn,account,identifier):
    with transaction(conn):
        saved=conn.execute('SELECT * FROM import_previews WHERE account_id=? AND preview_id=?',(account,identifier)).fetchone()
        if saved is None:_error('import_preview_not_found',404)
        if saved['state']=='committed':return {**json.loads(saved['result_json']),'already_committed':True}
        if saved['expires_at']<time.time():_error('import_preview_expired',409)
        payload=json.loads(saved['payload_json']);issues=list(payload['issues'])
        counts={'inserted':0,'unchanged':0,'rejected':payload['rejected'],'total':payload['total']}
        for item in payload['records']:
            rows=item.get('rows',[item['row']])
            room=conn.execute('SELECT kind FROM conversations WHERE account_id=? AND conversation_id=?',
                (account,item['record']['conversation_id'])).fetchone()
            issue='conversation_kind_conflict' if room and room[0]!=item['conversation_kind'] else None
            status=_classification(conn,item)
            if status=='conflict' and issue is None:issue='message_identity_conflict'
            if issue:
                counts['rejected']+=len(rows)
                issues.extend({'row':number,'code':issue} for number in rows[:100-len(issues)])
                continue
            if status=='unchanged':counts['unchanged']+=len(rows);continue
            record=MessageRecord.model_validate(item['record'])
            page=SourcePage(account_id=account,conversation_id=record.conversation_id,conversation_kind=item['conversation_kind'],records=[record],next_cursor=None,complete=False)
            delta=_archive_page_locked(conn,page,preserve_cursor=True,imports_only=True)
            counts['inserted']+=delta.inserted
            counts['unchanged']+=len(rows)-1
        result={'status':'committed','preview_id':identifier,'counts':counts,'issues':issues,'already_committed':False}
        conn.execute("UPDATE import_previews SET state='committed',payload_json='{}',result_json=? WHERE account_id=? AND preview_id=?",
                     (json.dumps(result,ensure_ascii=False),account,identifier))
    return result
