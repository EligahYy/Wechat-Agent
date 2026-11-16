"""Versioned non-secret settings; Keychain owns all credential bytes."""
import json
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field,SecretStr,StrictInt,field_validator,model_validator
from .contracts import ModelCallError
from .probe import ModelProbeConfig
from ..operations.service import OperationError
from ..source.repository import transaction

class ModelSettingsUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_id:str=Field(min_length=1,max_length=512)
    expected_version:StrictInt=Field(ge=0,le=2**63-2)
    endpoint:str
    model_id:str=Field(min_length=1,max_length=256)
    response_mode:str='json_object'
    context_tokens:StrictInt=Field(gt=0,le=10000000)
    max_output_tokens:StrictInt=Field(ge=16,le=1000000)
    api_key:SecretStr|None=None

    @field_validator('endpoint')
    @classmethod
    def endpoint_safe(cls,value):return ModelProbeConfig.credential_safe_endpoint(value)
    @model_validator(mode='after')
    def valid_values(self):
        if self.response_mode not in ('text','json_object','json_schema'):raise ValueError('response_mode_invalid')
        if not self.model_id.strip() or any(not c.isprintable() for c in self.model_id):raise ValueError('model_id_invalid')
        if self.max_output_tokens>self.context_tokens:raise ValueError('output_exceeds_context')
        if self.api_key is not None:
            key=self.api_key.get_secret_value()
            if not 1<=len(key)<=16384 or any(not 33<=ord(c)<=126 for c in key):raise ValueError('credential_invalid')
        return self

def read_saved(conn,account):
    row=conn.execute("SELECT value_json,version FROM settings WHERE account_id=? AND name='model_config'",(account,)).fetchone()
    return (json.loads(row[0]),row[1]) if row else (None,0)

def public_settings(conn,account):
    saved,version=read_saved(conn,account)
    result={'account_id':account,'version':version,'configured':saved is not None,'connection':{'state':'not_checked','capacity_verified':False,'vision_verified':False}}
    if saved:
        result.update({key:saved[key] for key in ('config_version','endpoint','model_id','response_mode','context_tokens','max_output_tokens')})
        check=conn.execute('SELECT state,code,finished_at,expires_at FROM model_connection_checks WHERE account_id=? AND config_version=? ORDER BY started_at DESC,rowid DESC LIMIT 1',(account,version)).fetchone()
        if check:
            import time
            expired=check['state']=='running' and check['expires_at']<=time.time()
            result['connection'].update(state='interrupted' if expired else check['state'],code='check_interrupted' if expired else check['code'],checked_at=check['finished_at'])
    result['runtime_ready']=False
    result['budget_review']=None
    result['budget_reference']=None
    review=conn.execute('SELECT reference,reviewed_at FROM model_budget_reviews WHERE account_id=? AND config_version=?',(account,version)).fetchone()
    if review:
        result['budget_review']={'method':'operator_document_review','reference':review['reference'],'reviewed_at':review['reviewed_at']}
        result['runtime_ready']=result['connection']['state']=='passed'
        result['budget_reference']=review['reference']
    elif saved:
        # Reuse documentation as an input suggestion, never as approval for a
        # different config version. Keep it scoped to this account and model.
        previous=conn.execute('''SELECT r.reference FROM model_budget_reviews r
            JOIN model_config_versions v ON v.account_id=r.account_id AND v.version=r.config_version
            WHERE r.account_id=? AND r.config_version<?
              AND json_extract(v.value_json,'$.endpoint')=?
              AND json_extract(v.value_json,'$.model_id')=?
            ORDER BY r.config_version DESC LIMIT 1''',
            (account,version,saved['endpoint'],saved['model_id'])).fetchone()
        if previous:result['budget_reference']=previous['reference']
    return result

def save_settings(conn,body,credentials):
    old,version=read_saved(conn,body.account_id)
    if version!=body.expected_version:raise OperationError('model_version_conflict',409)
    if body.api_key is None and (old is None or old['endpoint']!=body.endpoint):
        raise OperationError('model_new_key_required',422)
    ref='model:'+str(uuid4()) if body.api_key is not None else old['credential_ref']
    if body.api_key is not None:credentials.set(ref,body.api_key.get_secret_value())
    saved=body.model_dump(exclude={'api_key','account_id','expected_version'})
    saved.update(credential_ref=ref,config_version=str(uuid4()))
    with transaction(conn):
        _,current=read_saved(conn,body.account_id)
        if current!=body.expected_version:raise OperationError('model_version_conflict',409)
        conn.execute('INSERT INTO accounts(account_id) VALUES(?) ON CONFLICT DO NOTHING',(body.account_id,))
        conn.execute('INSERT INTO model_config_versions(account_id,version,value_json) VALUES(?,?,?)',(body.account_id,current+1,json.dumps(saved)))
        conn.execute("INSERT INTO settings(account_id,name,value_json,version) VALUES(?,'model_config',?,?) ON CONFLICT(account_id,name) DO UPDATE SET value_json=excluded.value_json,version=excluded.version",(body.account_id,json.dumps(saved),current+1))
    return public_settings(conn,body.account_id)


def load_runtime_config(conn,account,config_version,verified_capabilities):
    """Consumers must supply actual capacity evidence; a connection is insufficient."""
    from .contracts import ModelConfig,ModelCapabilities
    if verified_capabilities is None:raise ModelCallError('model_capabilities_unverified')
    capabilities=ModelCapabilities.model_validate(verified_capabilities)
    row=conn.execute("SELECT version,value_json FROM model_config_versions WHERE account_id=? AND json_extract(value_json,'$.config_version')=?",(account,config_version)).fetchone()
    if row is None:raise ModelCallError('model_config_missing')
    saved=json.loads(row['value_json'])
    check=conn.execute('SELECT state FROM model_connection_checks WHERE account_id=? AND config_version=? ORDER BY started_at DESC,rowid DESC LIMIT 1',(account,row['version'])).fetchone()
    if check is None or check['state']!='passed':raise ModelCallError('model_connection_unverified')
    if capabilities.model_id!=saved['model_id']:raise ModelCallError('model_capabilities_mismatch')
    # Declared limits can restrict verified capacity, never increase it.
    constrained=capabilities.model_copy(update={'context_tokens':min(capabilities.context_tokens,saved['context_tokens']),
        'max_output_tokens':min(capabilities.max_output_tokens,saved['max_output_tokens'],saved['context_tokens'])})
    return ModelConfig(version=saved['config_version'],endpoint=saved['endpoint'],model_id=saved['model_id'],credential_ref=saved['credential_ref'],response_mode=saved['response_mode'],capabilities=constrained)
