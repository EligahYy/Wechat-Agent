"""Explicit operator documentation review; never inferred from a short probe."""
from datetime import datetime,timezone
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictInt,StrictBool,field_validator
from .probe import ModelProbeConfig
from .settings import read_saved,public_settings
from .contracts import ModelCapabilities,ModelCallError
from ..operations.service import OperationError
from ..source.repository import transaction

class BudgetReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    account_id:str=Field(min_length=1,max_length=512)
    expected_version:StrictInt=Field(gt=0)
    reference:str=Field(max_length=2048)
    acknowledged:StrictBool
    schema_supported:StrictBool=False

    @field_validator('acknowledged')
    @classmethod
    def explicitly_confirmed(cls,value):
        if value is not True:raise ValueError('budget_review_required')
        return value

    @field_validator('reference')
    @classmethod
    def safe_reference(cls,value):return ModelProbeConfig.credential_safe_endpoint(value)

def review_budget(conn,body):
    with transaction(conn):
        saved,version=read_saved(conn,body.account_id)
        if not saved or version!=body.expected_version:raise OperationError('model_version_conflict',409)
        state=public_settings(conn,body.account_id)
        if state['connection']['state']!='passed':raise OperationError('model_connection_unverified',409)
        if saved['response_mode']=='json_schema' and not body.schema_supported:raise OperationError('model_schema_unverified',422)
        stamp=datetime.now(timezone.utc)
        caps=ModelCapabilities(model_id=saved['model_id'],context_tokens=saved['context_tokens'],max_output_tokens=saved['max_output_tokens'],structured_output=body.schema_supported,vision=False,verified_at=stamp)
        conn.execute('INSERT INTO model_budget_reviews VALUES(?,?,?,?,?) ON CONFLICT(account_id,config_version) DO UPDATE SET reference=excluded.reference,capabilities_json=excluded.capabilities_json,reviewed_at=excluded.reviewed_at',
            (body.account_id,version,body.reference,caps.model_dump_json(),stamp.isoformat()))
    return public_settings(conn,body.account_id)

def reviewed_capabilities(conn,account,version):
    row=conn.execute('SELECT * FROM model_budget_reviews WHERE account_id=? AND config_version=?',(account,version)).fetchone()
    if not row:raise ModelCallError('model_budget_unverified')
    return json.loads(row['capabilities_json'])
