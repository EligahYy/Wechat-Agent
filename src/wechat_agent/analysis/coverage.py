"""Material coverage is computed from primary spans, not from model assertions."""
from dataclasses import dataclass
import json

@dataclass(frozen=True)
class Coverage:
    processed:list[str]
    failed:list[str]
    pending:list[str]
    complete:bool


def span_coverage(expected,parts):
    if not expected or not parts:return False
    cursor=0
    for span,state in sorted(parts,key=lambda p:p[0]['start']):
        if state!='succeeded' or span['revision']!=expected['revision'] or span['total']!=expected['total'] or span['start']!=cursor or not 0<=span['start']<=span['end']<=expected['total']:return False
        cursor=span['end']
    return cursor==expected['total']


def compute_coverage(conn,account,snapshot_id):
    saved=conn.execute('SELECT s.manifest_json,h.materials_json FROM snapshots s LEFT JOIN history_runs h ON h.account_id=s.account_id AND h.snapshot_id=s.snapshot_id WHERE s.account_id=? AND s.snapshot_id=?',(account,snapshot_id)).fetchone()
    if not saved:raise ValueError('snapshot_not_authorized')
    refs={r['message_id']:r['revision'] for r in json.loads(saved['manifest_json'])['material_refs']}
    materials=json.loads(saved['materials_json']) if saved['materials_json'] else {}
    authorized={k:v['revision'] for k,v in materials.items()}==refs
    states={key:[] for key in refs}
    rows=conn.execute('SELECT phase,state,primary_json FROM history_run_units WHERE account_id=? AND snapshot_id=?',(account,snapshot_id)).fetchall()
    for row in rows:
        if row['phase']!='extract':continue
        for span in json.loads(row['primary_json']):
            if span['message_id'] not in refs or refs[span['message_id']]!=span['revision']:authorized=False
            else:states[span['message_id']].append((span,row['state']))
    processed=[];failed=[];pending=[]
    for key,parts in states.items():
        if span_coverage(materials.get(key),parts):processed.append(key)
        elif any(state=='failed' for _,state in parts):failed.append(key)
        else:pending.append(key)
    complete=authorized and not failed and not pending and bool(rows) and all(r['state']=='succeeded' for r in rows)
    return Coverage(sorted(processed),sorted(failed),sorted(pending),complete)
