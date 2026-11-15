"""Manual scope overrides precede every automatic admission reason."""
from datetime import datetime,timedelta,timezone
import json
from pydantic import BaseModel,Field
from ..source.contracts import ContactKey
from ..source.repository import transaction
from .activity import derive_activity,instant

class ScopeDecision(BaseModel):
    included:bool
    reasons:list[str]=Field(default_factory=list)
    provisional:bool=False
    version:int=0
class ScopeItem(BaseModel):
    key:ContactKey
    included:bool
    version:int
class ScopeFailure(BaseModel):
    key:ContactKey
    code:str
    current_version:int|None=None
class ScopeUpdateResult(BaseModel):
    updated:list[ScopeItem]=Field(default_factory=list)
    failed:list[ScopeFailure]=Field(default_factory=list)

def decisions(conn,account,now=None,contact_ids=None):
    now=now or datetime.now(timezone.utc)
    if now.utcoffset() is None:raise ValueError('scope_time_timezone_required')
    now=now.astimezone(timezone.utc);cutoff=now-timedelta(days=90)
    people={row["contact_id"]:row for row in conn.execute("SELECT * FROM contacts WHERE account_id=?",(account,)) if contact_ids is None or row["contact_id"] in contact_ids}
    overrides={row['contact_id']:row for row in conn.execute('SELECT * FROM business_scope_overrides WHERE account_id=?',(account,))}
    signals={row['contact_id']:row for row in conn.execute('SELECT * FROM business_signals WHERE account_id=?',(account,))}
    if any(person["role"]=="unknown" and key not in overrides for key,person in people.items()):
        _,activity,generation=derive_activity(conn,account)
    else:activity={};generation=None
    result={}
    for key,person in people.items():
        override=overrides.get(key);decision=ScopeDecision(included=False,version=override['version'] if override else 0)
        if person['is_self'] or person['identity_state']!='active':result[key]=decision;continue
        if override:
            decision.included=bool(override['included']);decision.reasons=['manual_include' if decision.included else 'manual_exclude']
        else:
            if person['role']!='unknown':decision.reasons.append('confirmed_role')
            material=activity.get(key,{})
            for kind,reason in [('private','recent_private'),('direct','direct_interaction')]:
                if any(cutoff<=instant(item['sent_at'])<=now for item in material.get(kind,[])):decision.reasons.append(reason)
            recent={item['message_id']:item for item in material.get('group',[]) if cutoff<=instant(item['sent_at'])<=now}
            if recent:
                signal=signals.get(key);valid=False
                if signal and signal['generation']==generation:
                    refs=json.loads(signal['sources_json'])
                    valid=bool(refs) and all(ref.get('message_id') in recent and recent[ref['message_id']]['revision']==ref.get('revision') for ref in refs)
                    if valid and signal['intent']=='request':decision.reasons.append('group_demand')
                if not valid or not signal['coverage_complete'] or signal['intent']=='uncertain':
                    decision.reasons.append('group_discovery_pending');decision.provisional=True
            decision.included=bool(decision.reasons)
        result[key]=decision
    return result

def classify_scope(conn,key,now):
    key=ContactKey.model_validate(key)
    return decisions(conn,key.account_id,now).get(key.contact_id,ScopeDecision(included=False))

def set_scope(conn,keys,included,expected_versions):
    if type(included) is not bool:raise ValueError('scope_included_boolean_required')
    keys=[ContactKey.model_validate(key) for key in keys]
    if not keys or len(set(keys))!=len(keys) or len({key.account_id for key in keys})!=1:raise ValueError('invalid_scope_batch')
    result=ScopeUpdateResult()
    with transaction(conn):
        for key in keys:
            person=conn.execute('SELECT is_self,identity_state FROM contacts WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()
            saved=conn.execute('SELECT version FROM business_scope_overrides WHERE account_id=? AND contact_id=?',(key.account_id,key.contact_id)).fetchone()
            version=saved[0] if saved else 0
            code='contact_not_available' if person is None or person['is_self'] or person['identity_state']!='active' else 'scope_version_conflict' if type(expected_versions.get(key.contact_id)) is not int or expected_versions[key.contact_id]!=version else None
            if code:result.failed.append(ScopeFailure(key=key,code=code,current_version=version));continue
            conn.execute("INSERT INTO business_scope_overrides(account_id,contact_id,included,version) VALUES(?,?,?,?) ON CONFLICT(account_id,contact_id) DO UPDATE SET included=excluded.included,version=excluded.version,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",(key.account_id,key.contact_id,int(included),version+1))
            if not included:
                conn.execute("UPDATE operation_items SET state='stopped',generation=generation+1,error_code='contact_scope_excluded' WHERE account_id=? AND contact_id=? AND phase='analysis' AND state='queued'",(key.account_id,key.contact_id))
            result.updated.append(ScopeItem(key=key,included=included,version=version+1))
    return result

def business_scope_allows_analysis(conn,key):
    person=conn.execute("SELECT 1 FROM contacts WHERE account_id=? AND contact_id=? AND role='merchant' AND is_self=0 AND identity_state='active'",(key.account_id,key.contact_id)).fetchone()
    return bool(person) and classify_scope(conn,key,datetime.now(timezone.utc)).included
