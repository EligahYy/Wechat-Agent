"""Validate evidence authorization and local numeric/date consistency, not model semantics."""
from dataclasses import dataclass,field
from datetime import datetime
from decimal import Decimal
import re
from pydantic import ValidationError
from .contracts import AnalysisResult,Fact
from ..context.reader import ContextReader
from ..context.contracts import SnapshotError

@dataclass
class ValidationResult:
    result:AnalysisResult|None=None
    issues:list[str]=field(default_factory=list)
    reason:str|None=None


def _numbers(text):
    return {Decimal(n) for n in re.findall(r'(?<![\d.])\d+(?:\.\d+)?(?![\d.])',text)}


def _units(text):
    aliases={'立方米':'cbm','方':'cbm','m³':'cbm','m3':'cbm','千克':'kg','公斤':'kg','吨':'ton','t':'ton','元':'rmb','人民币':'rmb','美元':'usd','欧元':'eur'}
    pattern=r'(\d+(?:\.\d+)?)\s*(立方米|cbm|m³|m3|千克|公斤|kg|人民币|美元|欧元|rmb|usd|eur|方|吨|元|t|%)'
    return {(Decimal(n),aliases.get(unit.lower(),unit.lower())) for n,unit in re.findall(pattern,text,re.I)}


def validate_result(conn,snapshot,result,*,reader=None):
    try:
        if reader is None:reader=ContextReader(conn,snapshot)
        elif not isinstance(reader,ContextReader) or reader.snapshot!=snapshot:raise SnapshotError("snapshot_not_authorized")
    except (SnapshotError,ValidationError,ValueError):return ValidationResult(reason='snapshot_not_authorized')
    try:result=AnalysisResult.model_validate(result.model_dump() if isinstance(result,AnalysisResult) else result)
    except (ValidationError,TypeError,ValueError):return ValidationResult(reason='output_invalid')
    if result.contact_id!=snapshot.key.contact_id:return ValidationResult(reason='target_mismatch')
    result=result.model_copy(deep=True);issues=[]
    def issue_reason(error):
        code = str(error)
        return code if code in {
            'sources_missing', 'source_not_interpretable', 'attachment_not_processed',
            'number_not_supported', 'unit_not_supported', 'event_date_not_supported',
            'duplicate_candidate_key', 'shipment_outside_contact',
        } else 'evidence_invalid'
    def evidence(refs):
        if not refs:raise ValueError('sources_missing')
        rows=[reader.resolve(ref) for ref in refs]
        if any(ref.attachment_id or ref.locator for ref in refs):raise ValueError('attachment_not_processed')
        if any(row['kind'] not in ('text','quote') or row['author_state']!='active' or not row['body'].strip() for row in rows):raise ValueError('source_not_interpretable')
        return rows
    def check(fact,path):
        if fact.state=='not_mentioned':return fact
        if not fact.value:
            if fact.sources:
                try:evidence(fact.sources)
                except ValueError:issues.append(path+':source_invalid');return Fact()
            return fact
        try:
            rows=evidence(fact.sources);text='\n'.join(row['body'] for row in rows)
            if not _numbers(fact.value)<=_numbers(text):raise ValueError('number_not_supported')
            if not _units(fact.value)<=_units(text):raise ValueError('unit_not_supported')
            if fact.event_time:
                day=fact.event_time.date().isoformat()
                dates={datetime.fromisoformat(row['sent_at'].replace('Z','+00:00')).astimezone(fact.event_time.tzinfo).date().isoformat() for row in rows}
                explicit={f'{int(y):04}-{int(m):02}-{int(d):02}' for y,m,d in re.findall(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})',text)}
                if day not in dates|explicit:raise ValueError('event_date_not_supported')
            return fact
        except (ValueError,SnapshotError) as error:
            issues.append(f'{path}:{issue_reason(error)}')
            return Fact()
    for group in ('goods','logistics'):
        fields=getattr(result,group)
        for name in type(fields).model_fields:setattr(fields,name,check(getattr(fields,name),group+'.'+name))
    result.communication.summary=check(result.communication.summary,'communication.summary')
    shipments=[];seen=set()
    for i,batch in enumerate(result.shipments):
        path=f'shipments.{i}'
        try:
            rows=evidence(batch.sources)
            if batch.candidate_key in seen:raise ValueError('duplicate_candidate_key')
            seen.add(batch.candidate_key)
            if batch.existing_id and not conn.execute('SELECT 1 FROM shipments WHERE account_id=? AND contact_id=? AND shipment_id=?',(snapshot.key.account_id,snapshot.key.contact_id,batch.existing_id)).fetchone():raise ValueError('shipment_outside_contact')
            if any(number.strip() not in '\n'.join(r['body'] for r in rows) or not number.strip() for number in batch.numbers):raise ValueError('number_not_supported')
            batch.goods=[check(f,path+'.goods') for f in batch.goods]
            batch.logistics=[check(f,path+'.logistics') for f in batch.logistics]
            shipments.append(batch)
        except (ValueError,SnapshotError) as error:
            issues.append(f'{path}:{issue_reason(error)}')
    result.shipments=shipments
    if result.communication.tags and result.communication.summary.state=='not_mentioned':
        result.communication.tags=[]
        if not any(issue.startswith('communication.summary:') for issue in issues):
            issues.append('communication.tags:summary_missing')
    stamp=result.communication.last_business_at
    if stamp and stamp not in {datetime.fromisoformat(row['sent_at'].replace('Z','+00:00')) for row in reader.messages() if row['kind'] not in ('system','revoke')}:
        result.communication.last_business_at=None;issues.append('communication.last_business_at:time_not_supported')
    facts=[getattr(getattr(result,g),name) for g in ('goods','logistics') for name in type(getattr(result,g)).model_fields]+[result.communication.summary]
    if not shipments and not any(f.value for f in facts):return ValidationResult(issues=issues,reason='empty_result')
    return ValidationResult(result,issues)
