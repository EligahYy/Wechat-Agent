"""Account-scoped content checkpoints and operation-owned progress; no new queue."""
from dataclasses import asdict
import hashlib
import json
from ..source.repository import transaction,cancellation_requested
from ..model.contracts import ModelCallError
from ..context.tokens import ESTIMATOR,request_budget
from ..operations.service import now
from .coverage import compute_coverage


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def create_run(conn,snapshot,token,mode,config):
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        conn.execute('''INSERT INTO history_runs(account_id,snapshot_id,contact_id,operation_id,strategy,estimator,mode,context_tokens)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
            (snapshot.key.account_id,snapshot.id,snapshot.key.contact_id,token.operation_id,'chunked-text-v1',ESTIMATOR,mode,config.capabilities.context_tokens))


def register_unit(conn,snapshot,token,request,primary,ordinal,config):
    key=digest({'policy':'chunked-text-v1','account':snapshot.key.account_id,'contact':snapshot.key.contact_id,
        'role':snapshot.role_version,'manual':snapshot.manual_version,'scope':snapshot.scope_version,
        'profile':snapshot.profile_version,'versions':snapshot.versions,'coverage':snapshot.coverage.model_dump() if snapshot.coverage else None,
        'phase':request.phase,'messages':[m.model_dump() for m in request.messages],
        'schema':request.output_schema,'output':request.output_tokens,'primary':[asdict(s) for s in primary]})
    unit='h:'+digest([snapshot.id,token.operation_id,key])
    request=request.model_copy(update={'unit_id':unit,'call_id':unit,'checkpoint_key':key})
    budget=request_budget(request,config)
    if not budget.fits:raise ModelCallError('context_requires_chunking')
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        conn.execute('''INSERT INTO history_checkpoints(account_id,contact_id,cache_key,phase,state)
            VALUES(?,?,?,?,'pending') ON CONFLICT DO NOTHING''',(snapshot.key.account_id,snapshot.key.contact_id,key,request.phase))
        conn.execute('''INSERT INTO history_run_units(account_id,snapshot_id,contact_id,unit_id,cache_key,phase,ordinal,state,input_tokens,output_tokens,primary_json,request_json)
            VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?) ON CONFLICT DO NOTHING''',
            (snapshot.key.account_id,snapshot.id,snapshot.key.contact_id,unit,key,request.phase,ordinal,budget.input_tokens,request.output_tokens,
             canonical([asdict(s) for s in primary]),request.model_dump_json()))
    return request


def checkpoint(conn,snapshot,request):
    return conn.execute('SELECT * FROM history_checkpoints WHERE account_id=? AND contact_id=? AND cache_key=?',
        (snapshot.key.account_id,snapshot.key.contact_id,request.checkpoint_key)).fetchone()


def set_unit(conn,snapshot,token,request,state,*,output=None,error=None,reused=False):
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        if not reused:
            conn.execute('''UPDATE history_checkpoints SET state=?,output_json=?,error_code=?
                WHERE account_id=? AND contact_id=? AND cache_key=?''',
                (state,output.model_dump_json() if output is not None else None,error,snapshot.key.account_id,snapshot.key.contact_id,request.checkpoint_key))
        conn.execute('''UPDATE history_run_units SET state=?,reused=?,error_code=? WHERE account_id=? AND snapshot_id=? AND unit_id=?''',
            (state,int(reused),error,snapshot.key.account_id,snapshot.id,request.unit_id))
    update_progress(conn,snapshot,token)


def update_progress(conn,snapshot,token):
    account=snapshot.key.account_id
    with transaction(conn):
        if cancellation_requested(conn,account,token):raise ModelCallError('model_cancelled')
        rows=conn.execute('SELECT phase,state,reused FROM history_run_units WHERE account_id=? AND snapshot_id=?',(account,snapshot.id)).fetchall()
        progress={}
        for phase,label in [('extract','chunks'),('merge','merge')]:
            items=[r for r in rows if r['phase']==phase]
            for name,value in [('total',len(items)),('completed',sum(r['state']=='succeeded' for r in items)),('failed',sum(r['state']=='failed' for r in items)),('reused',sum(r['reused'] for r in items))]:
                progress[f'analysis_{label}_{name}']=value
        coverage=compute_coverage(conn,account,snapshot.id)
        progress.update(analysis_material_total=len(snapshot.material_refs),analysis_material_completed=len(coverage.processed))
        conn.execute('UPDATE history_runs SET progress_json=? WHERE account_id=? AND snapshot_id=?',(canonical(progress),account,snapshot.id))
        aggregate={}
        for run in conn.execute('SELECT progress_json FROM history_runs WHERE account_id=? AND operation_id=?',(account,token.operation_id)):
            for key,value in json.loads(run[0]).items():aggregate[key]=aggregate.get(key,0)+value
        counts=json.loads(conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',(account,token.operation_id)).fetchone()[0])
        counts.update(aggregate)
        conn.execute('UPDATE operations SET counts_json=?,updated_at=? WHERE account_id=? AND id=?',(canonical(counts),now(),account,token.operation_id))
