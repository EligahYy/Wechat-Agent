"""Account-scoped content checkpoints and operation-owned progress; no new queue."""
from dataclasses import asdict
import hashlib
import json
from ..source.repository import transaction,cancellation_requested
from ..model.contracts import ModelCallError
from ..context.tokens import ESTIMATOR,request_budget
from ..operations.service import now
from .coverage import span_coverage


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def create_run(conn,snapshot,token,mode,config,*,messages=None):
    if messages is None:
        from ..context.reader import ContextReader
        messages=ContextReader(conn,snapshot).messages()
    materials={r['message_id']:{'revision':r['revision'],'total':len(r['body'])} for r in messages}
    if {(k,v['revision']) for k,v in materials.items()}!={(r.message_id,r.revision) for r in snapshot.material_refs}:
        raise ModelCallError('snapshot_not_authorized')
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        conn.execute('''INSERT INTO history_runs(account_id,snapshot_id,contact_id,operation_id,strategy,estimator,mode,context_tokens,materials_json)
            VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
            (snapshot.key.account_id,snapshot.id,snapshot.key.contact_id,token.operation_id,'chunked-text-v1',ESTIMATOR,mode,config.capabilities.context_tokens,canonical(materials)))


def material_dependencies(payload):
    refs = {(row['message_id'], row['revision']) for row in payload.get('messages', [])}
    if payload.get('candidates'):
        from ..profiles.contracts import AnalysisResult
        from .facts import source_refs
        refs.update(
            (ref.message_id, ref.revision)
            for candidate in payload['candidates']
            for ref in source_refs(AnalysisResult.model_validate(candidate))
        )
    return sorted(refs)


def register_unit(conn,snapshot,token,request,primary,ordinal,config):
    payload = json.loads(request.messages[-1].content)
    reads_previous_profile = request.phase != 'extract' or 'history_unit' not in payload
    key=digest({'policy':'chunked-text-v1','account':snapshot.key.account_id,'contact':snapshot.key.contact_id,
        'role':snapshot.role_version,'manual':snapshot.manual_version,'scope':snapshot.scope_version,
        'profile':snapshot.profile_version if reads_previous_profile else None,'versions':snapshot.versions,'coverage':snapshot.coverage.model_dump() if reads_previous_profile and snapshot.coverage else None,
        'phase':request.phase,'messages':[m.model_dump() for m in request.messages],
        'schema':request.output_schema,'output':request.output_tokens,'primary':[asdict(s) for s in primary]})
    unit='h:'+digest([snapshot.id,token.operation_id,key])
    request=request.model_copy(update={'unit_id':unit,'call_id':unit,'checkpoint_key':key})
    dependencies = material_dependencies(payload)
    budget=request_budget(request,config)
    if not budget.fits:raise ModelCallError('context_requires_chunking')
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        conn.execute('''INSERT INTO history_checkpoints(account_id,contact_id,cache_key,phase,state)
            VALUES(?,?,?,?,'pending') ON CONFLICT DO NOTHING''',(snapshot.key.account_id,snapshot.key.contact_id,key,request.phase))
        conn.executemany(
            'INSERT INTO history_checkpoint_refs VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING',
            ((snapshot.key.account_id, snapshot.key.contact_id, key, identifier, revision)
             for identifier, revision in dependencies),
        )
        conn.execute('''INSERT INTO history_run_units(account_id,snapshot_id,contact_id,unit_id,cache_key,phase,ordinal,state,input_tokens,output_tokens,primary_json,request_json)
            VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?) ON CONFLICT DO NOTHING''',
            (snapshot.key.account_id,snapshot.id,snapshot.key.contact_id,unit,key,request.phase,ordinal,budget.input_tokens,request.output_tokens,
             canonical([asdict(s) for s in primary]),request.model_dump_json()))
    return request


def checkpoint(conn,snapshot,request):
    identity = (snapshot.key.account_id, snapshot.key.contact_id, request.checkpoint_key)
    saved = conn.execute('SELECT * FROM history_checkpoints WHERE account_id=? AND contact_id=? AND cache_key=?',
                         identity).fetchone()
    if saved['state'] == 'succeeded' and conn.execute(
        """SELECT 1 FROM history_checkpoint_refs r LEFT JOIN messages m
           ON m.account_id=r.account_id AND m.message_id=r.message_id AND m.revision=r.revision
           WHERE r.account_id=? AND r.contact_id=? AND r.cache_key=? AND m.message_id IS NULL LIMIT 1""",
        identity,
    ).fetchone():
        raise ModelCallError('material_changed')
    return saved


def set_unit(conn,snapshot,token,request,state,*,output=None,error=None,reused=False,progress=None):
    with transaction(conn):
        if cancellation_requested(conn,snapshot.key.account_id,token):raise ModelCallError('model_cancelled')
        if not reused:
            conn.execute('''UPDATE history_checkpoints SET state=?,output_json=?,error_code=?
                WHERE account_id=? AND contact_id=? AND cache_key=?''',
                (state,output.model_dump_json(exclude_defaults=True, exclude_none=True) if output is not None else None,error,snapshot.key.account_id,snapshot.key.contact_id,request.checkpoint_key))
        conn.execute('''UPDATE history_run_units SET state=?,reused=?,error_code=? WHERE account_id=? AND snapshot_id=? AND unit_id=?''',
            (state,int(reused),error,snapshot.key.account_id,snapshot.id,request.unit_id))
    if progress is None:progress=RunProgress(conn,snapshot,token)
    else:progress.changed(request.unit_id,state,reused)
    progress.persist()


class RunProgress:
    """One in-memory index per frozen run; persist counters, not repeated scans."""
    def __init__(self,conn,snapshot,token):
        self.conn,self.snapshot,self.token=conn,snapshot,token
        saved=conn.execute('SELECT context_tokens,materials_json FROM history_runs WHERE account_id=? AND snapshot_id=?',(snapshot.key.account_id,snapshot.id)).fetchone()
        self.materials=json.loads(saved['materials_json'])
        self.window=saved['context_tokens'];self.units={};self.done_parts={};self.parts={};self.covered=set()
        self.values={f'analysis_{phase}_{name}':0 for phase in ('chunks','merge') for name in ('total','completed','failed','reused')}
        self.values['analysis_refinements']=conn.execute('SELECT COUNT(DISTINCT parent_id) FROM history_refinements WHERE account_id=? AND snapshot_id=?',(snapshot.key.account_id,snapshot.id)).fetchone()[0]
        self.values.update(analysis_context_tokens=self.window,analysis_max_input_tokens=0,analysis_max_output_tokens=0)
        self.load()

    def load(self,*,merge_only=False,unit_id=None):
        sql='SELECT * FROM history_run_units WHERE account_id=? AND snapshot_id=? AND superseded=0'
        if merge_only:sql+=" AND phase='merge'"
        params = (self.snapshot.key.account_id, self.snapshot.id)
        if unit_id is not None:
            sql += " AND unit_id=?"
            params += (unit_id,)
        for row in self.conn.execute(sql,params):
            if row['unit_id'] in self.units:continue
            item=dict(row);item['primary']=json.loads(item['primary_json']);self.units[item['unit_id']]=item
            label='chunks' if item['phase']=='extract' else 'merge'
            self.values[f'analysis_{label}_total']+=1
            self.values['analysis_max_input_tokens']=max(self.values['analysis_max_input_tokens'],item['input_tokens'])
            self.values['analysis_max_output_tokens']=max(self.values['analysis_max_output_tokens'],item['output_tokens'])
            for span in item['primary']:
                key=span['message_id'];self.parts.setdefault(key,[]).append(span)
            self._account(item,1)
        if merge_only:
            return
        self.valid_materials={key for key,parts in self.parts.items() if span_coverage(self.materials.get(key),[(p,'succeeded') for p in parts])}
        self.covered={k for k in self.valid_materials if self.done_parts.get(k,0)==len(self.parts[k])}

    def _account(self,item,delta):
        label='chunks' if item['phase']=='extract' else 'merge'
        if item['state']=='succeeded':self.values[f'analysis_{label}_completed']+=delta
        if item['state']=='failed':self.values[f'analysis_{label}_failed']+=delta
        self.values[f'analysis_{label}_reused']+=delta*item['reused']
        if item['state']=='succeeded':
            for span in item['primary']:
                key=span['message_id'];self.done_parts[key]=self.done_parts.get(key,0)+delta

    def changed(self,unit_id,state,reused):
        item=self.units[unit_id];self._account(item,-1)
        item.update(state=state,reused=int(reused));self._account(item,1)
        for span in item['primary']:
            key=span['message_id']
            if key in self.valid_materials and self.done_parts.get(key,0)==len(self.parts[key]):self.covered.add(key)
            else:self.covered.discard(key)

    def persist(self):
        account=self.snapshot.key.account_id
        progress={**self.values,'analysis_material_total':len(self.materials),'analysis_material_completed':len(self.covered)}
        with transaction(self.conn):
            if cancellation_requested(self.conn,account,self.token):raise ModelCallError('model_cancelled')
            self.conn.execute('UPDATE history_runs SET progress_json=? WHERE account_id=? AND snapshot_id=?',(canonical(progress),account,self.snapshot.id))
            aggregate={}
            for run in self.conn.execute('SELECT progress_json FROM history_runs WHERE account_id=? AND operation_id=?',(account,self.token.operation_id)):
                for key,value in json.loads(run[0]).items():
                    aggregate[key]=max(aggregate.get(key,0),value) if key in {'analysis_context_tokens','analysis_max_input_tokens','analysis_max_output_tokens'} else aggregate.get(key,0)+value
            counts=json.loads(self.conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',(account,self.token.operation_id)).fetchone()[0])
            counts.update(aggregate)
            self.conn.execute('UPDATE operations SET counts_json=?,updated_at=? WHERE account_id=? AND id=?',(canonical(counts),now(),account,self.token.operation_id))
