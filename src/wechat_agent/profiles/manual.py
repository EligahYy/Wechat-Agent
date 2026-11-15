"""Separate, versioned human overrides; model facts and evidence stay immutable."""
from datetime import datetime
import copy
import json
from typing import Literal
from pydantic import AwareDatetime,BaseModel,ConfigDict,Field,StrictStr,TypeAdapter,model_validator
from .contracts import AnalysisResult,Goods,Logistics,Communication
from ..operations.service import OperationError
from ..source.contracts import ContactKey
from ..source.repository import transaction

MAX_VERSION=2**63-2
FIELD_PATHS={*(f'goods.{name}' for name in Goods.model_fields),*(f'logistics.{name}' for name in Logistics.model_fields),'communication.summary','communication.tags','communication.last_business_at'}

class ManualPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fields:dict[str,StrictStr|list[StrictStr]|None]=Field(default_factory=dict,max_length=16)
    notes:dict[Literal['goods','logistics'],StrictStr|None]=Field(default_factory=dict,max_length=2)

    @model_validator(mode='after')
    def fixed_fields(self):
        for path,value in self.fields.items():
            if path not in FIELD_PATHS:raise ValueError('manual_field_unknown')
            if value is None:continue
            if path=='communication.tags':
                if not isinstance(value,list) or len(value)>7:raise ValueError('manual_tags_invalid')
                Communication(tags=value)
            elif path=='communication.last_business_at':
                if not isinstance(value,str):raise ValueError('manual_time_invalid')
                stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
                self.fields[path]=TypeAdapter(AwareDatetime).validate_python(stamp).isoformat()
            else:
                if not isinstance(value,str) or not value.strip() or len(value)>16000:raise ValueError('manual_value_invalid')
                self.fields[path]=value.strip()
        for value in self.notes.values():
            if value is not None and len(value)>8000:raise ValueError('manual_note_too_long')
        if not self.fields and not self.notes:raise ValueError('manual_patch_empty')
        return self


def contact_key(account,contact):
    try:return ContactKey(account_id=account,contact_id=contact)
    except ValueError:raise OperationError('profile_not_found',404) from None


def _contact(conn,key,*,editing=False):
    row=conn.execute("SELECT role FROM contacts WHERE account_id=? AND contact_id=? AND identity_state='active' AND is_self=0",(key.account_id,key.contact_id)).fetchone()
    if not row or (editing and row['role']!='merchant'):raise OperationError('profile_not_found',404)
    return row


def read_manual(conn,key):
    row=conn.execute('SELECT value_json FROM profile_manual WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()
    return json.loads(row[0]) if row else {'fields':{},'notes':{}}


def _event(conn,key,version,kind,before,after,shipment=None):
    conn.execute('''INSERT INTO profile_manual_events(account_id,contact_id,version,kind,shipment_id,before_json,after_json)
        VALUES(?,?,?,?,?,?,?)''',(key.account_id,key.contact_id,version,kind,shipment,json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False)))


def _bump(conn,key):
    conn.execute('''INSERT INTO profile_heads(account_id,contact_id,manual_version) VALUES(?,?,1)
        ON CONFLICT(account_id,contact_id) DO UPDATE SET manual_version=manual_version+1''',(key.account_id,key.contact_id))
    return conn.execute('SELECT manual_version FROM profile_heads WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()[0]


def save_manual(conn,key:ContactKey,patch:dict,expected_version:int)->int:
    key=ContactKey.model_validate(key)
    patch=ManualPatch.model_validate(patch)
    if type(expected_version) is not int or not 0<=expected_version<=MAX_VERSION:raise OperationError('manual_version_invalid',422)
    with transaction(conn):
        _contact(conn,key,editing=True)
        head=conn.execute('SELECT manual_version FROM profile_heads WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()
        version=head[0] if head else 0
        if version!=expected_version:raise OperationError('manual_version_conflict',409)
        before=read_manual(conn,key);after=copy.deepcopy(before)
        for name,value in patch.fields.items():
            if value is None:after['fields'].pop(name,None)
            else:after['fields'][name]=value
        for name,value in patch.notes.items():
            if value is None or not value.strip():after['notes'].pop(name,None)
            else:after['notes'][name]=value.strip()
        if after==before:return version
        version=_bump(conn,key)
        conn.execute('INSERT INTO profile_manual VALUES(?,?,?) ON CONFLICT(account_id,contact_id) DO UPDATE SET value_json=excluded.value_json',(key.account_id,key.contact_id,json.dumps(after,ensure_ascii=False)))
        _event(conn,key,version,'fields',before,after)
        return version


def read_profile(conn,key:ContactKey):
    key=ContactKey.model_validate(key);person=_contact(conn,key)
    head=conn.execute('SELECT * FROM profile_heads WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()
    version=head['version'] if head else 0;manual_version=head['manual_version'] if head else 0
    published=conn.execute('SELECT * FROM profile_versions WHERE account_id=? AND contact_id=? AND version=?',(key.account_id,key.contact_id,version)).fetchone() if version else None
    model=json.loads(published['result_json']) if published else None
    effective=copy.deepcopy(model) if model else AnalysisResult(contact_id=key.contact_id).model_dump(mode='json')
    for group in ('goods','logistics'):
        for fact in effective[group].values():fact['origin']='model' if fact['state']!='not_mentioned' else None
    effective['communication']['summary']['origin']='model' if effective['communication']['summary']['state']!='not_mentioned' else None
    manual=read_manual(conn,key)
    origins={};conflicts=[]
    for path,value in manual['fields'].items():
        group,name=path.split('.')
        if model:
            original=model[group][name]
            model_value=original.get('value') if isinstance(original,dict) else original
            differs=model_value!=value
            if path=='communication.last_business_at' and model_value and value:
                differs=datetime.fromisoformat(model_value.replace('Z','+00:00'))!=datetime.fromisoformat(value.replace('Z','+00:00'))
            if model_value not in (None,[], '') and differs:
                conflicts.append({'path':path,'model_value':model_value,'manual_value':value,'model_sources':original.get('sources',[]) if isinstance(original,dict) else []})
        if path in ('communication.tags','communication.last_business_at'):effective[group][name]=value
        else:effective[group][name]={'value':value,'state':'known','sources':[],'event_time':None,'batch_ref':None,'origin':'manual','manual_version':manual_version}
        origins[path]='manual'
    shipments=[]
    for row in conn.execute('SELECT * FROM shipments WHERE account_id=? AND contact_id=? ORDER BY shipment_id',(key.account_id,key.contact_id)):
        shipments.append({'shipment_id':row['shipment_id'],'stage':row['stage'],'details':json.loads(row['payload_json']),'numbers':json.loads(row['numbers_json']),'numbers_origin':row['numbers_origin'],'version':row['version']})
    effective['shipments']=shipments
    pending=bool(published['pending']) if published else False
    if published:
        manifest=conn.execute('SELECT manifest_json FROM snapshots WHERE account_id=? AND snapshot_id=?',(key.account_id,published['snapshot_id'])).fetchone()
        frozen=json.loads(manifest[0])
        pending|=manual_version!=frozen['manual_version']
        expected={(ref['message_id'],ref['revision']) for ref in frozen['material_refs']}
        current={(row[0],row[1]) for row in conn.execute('''SELECT message_id,revision FROM messages
            WHERE account_id=? AND conversation_id IN (SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?)
            UNION SELECT message_id,revision FROM messages WHERE account_id=? AND sender_id=?''',
            (key.account_id,key.account_id,key.contact_id,key.account_id,key.contact_id))}
        pending|=current!=expected
    return {'account_id':key.account_id,'contact_id':key.contact_id,'applicable':person['role']=='merchant','model_version':version,'manual_version':manual_version,
        'model':model,'manual':{**manual,'origin':'manual'},'effective':effective,'field_origins':origins,'conflicts':conflicts,'shipments':shipments,
        'complete':bool(published['complete']) and not pending if published else False,'pending':pending,'issues':json.loads(published['issues_json']) if published else []}


def save_numbers(conn,key:ContactKey,shipment_id:str,numbers:list[str],expected_version:int):
    key=ContactKey.model_validate(key)
    if type(expected_version) is not int or not 1<=expected_version<=MAX_VERSION:raise OperationError('shipment_version_invalid',422)
    if not isinstance(numbers,list) or len(numbers)>100 or any(not isinstance(n,str) or not n.strip() or len(n)>256 for n in numbers):raise OperationError('shipment_numbers_invalid',422)
    numbers=list(dict.fromkeys(n.strip() for n in numbers))
    with transaction(conn):
        _contact(conn,key,editing=True)
        row=conn.execute('SELECT * FROM shipments WHERE account_id=? AND contact_id=? AND shipment_id=?',(key.account_id,key.contact_id,shipment_id)).fetchone()
        if not row:raise OperationError('shipment_not_found',404)
        if row['version']!=expected_version:raise OperationError('shipment_version_conflict',409)
        previous=json.loads(row['numbers_json'])
        if previous!=numbers or row['numbers_origin']!='manual':
            version=_bump(conn,key)
            conn.execute("UPDATE shipments SET numbers_json=?,numbers_origin='manual',version=version+1 WHERE account_id=? AND shipment_id=?",(json.dumps(numbers,ensure_ascii=False),key.account_id,shipment_id))
            _event(conn,key,version,'numbers',{'numbers':previous,'origin':row['numbers_origin']},{'numbers':numbers,'origin':'manual'},shipment_id)
        row=conn.execute('SELECT * FROM shipments WHERE account_id=? AND shipment_id=?',(key.account_id,shipment_id)).fetchone()
        return {'shipment_id':shipment_id,'contact_id':key.contact_id,'account_id':key.account_id,'numbers':json.loads(row['numbers_json']),'origin':row['numbers_origin'],'version':row['version'],'stage':row['stage']}
