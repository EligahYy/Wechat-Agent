"""Replace truncated work with bounded, auditable complete sub-results."""
import json
from collections import defaultdict
from ..source.repository import transaction,cancellation_requested
from ..model.contracts import ModelCallError

MAX_DEPTH=3


def supersede(conn,snapshot,token,parent,children,progress,*,replaying_verified_plan=False):
    if not children:raise ModelCallError('output_truncated')
    account=snapshot.key.account_id
    with transaction(conn):
        if cancellation_requested(conn,account,token):raise ModelCallError('model_cancelled')
        old=conn.execute('SELECT * FROM history_run_units WHERE account_id=? AND snapshot_id=? AND unit_id=?',(account,snapshot.id,parent.unit_id)).fetchone()
        if not old or not (replaying_verified_plan and old['phase']=='extract' and old['state']=='pending'
                           or old['error_code'] in {'output_truncated', 'model_timeout'}
                           or (old['phase'] == 'merge' and old['error_code'] == 'history_merge_incomplete')):raise ModelCallError('refinement_invalid')
        rows=[]
        for child in children:
            row=conn.execute('SELECT * FROM history_run_units WHERE account_id=? AND snapshot_id=? AND unit_id=?',(account,snapshot.id,child.unit_id)).fetchone()
            if not row or row['phase']!=old['phase'] or child.unit_id==parent.unit_id:raise ModelCallError('refinement_invalid')
            rows.append(row)
        if old['phase']=='extract':
            required=defaultdict(list);provided=defaultdict(list)
            for span in json.loads(old['primary_json']):required[(span['message_id'],span['revision'],span['total'])].append((span['start'],span['end']))
            for row in rows:
                for span in json.loads(row['primary_json']):provided[(span['message_id'],span['revision'],span['total'])].append((span['start'],span['end']))
            def intervals(value):
                out=[]
                for start,end in sorted(value):
                    if out and start==out[-1][1]:out[-1]=(out[-1][0],end)
                    else:out.append((start,end))
                return out
            if set(required)!=set(provided) or any(intervals(required[k])!=intervals(provided[k]) for k in required):raise ModelCallError('refinement_invalid')
        for child in children:
            conn.execute('INSERT OR IGNORE INTO history_refinements VALUES(?,?,?,?)',(account,snapshot.id,parent.unit_id,child.unit_id))
        conn.execute('UPDATE history_run_units SET superseded=1 WHERE account_id=? AND snapshot_id=? AND unit_id=?',(account,snapshot.id,parent.unit_id))
        conn.execute("UPDATE history_runs SET mode='chunked' WHERE account_id=? AND snapshot_id=?",(account,snapshot.id))
    # Reindex only on a refinement, not on ordinary success/cache transitions.
    progress.__init__(conn,snapshot,token);progress.persist()
