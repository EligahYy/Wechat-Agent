"""Material coverage is computed from primary spans, not from model assertions."""
from dataclasses import dataclass
import json

@dataclass(frozen=True)
class Coverage:
    processed:list[str]
    failed:list[str]
    pending:list[str]
    complete:bool


def compute_coverage(conn,account,snapshot_id):
    saved=conn.execute('SELECT manifest_json FROM snapshots WHERE account_id=? AND snapshot_id=?',(account,snapshot_id)).fetchone()
    if not saved:raise ValueError('snapshot_not_authorized')
    refs={r['message_id']:r['revision'] for r in json.loads(saved[0])['material_refs']}
    states={key:[] for key in refs}
    rows=conn.execute('SELECT phase,state,primary_json FROM history_run_units WHERE account_id=? AND snapshot_id=?',(account,snapshot_id)).fetchall()
    for row in rows:
        if row['phase']!='extract':continue
        for span in json.loads(row['primary_json']):
            if refs.get(span['message_id'])==span['revision']:states[span['message_id']].append((span,row['state']))
    processed=[];failed=[];pending=[]
    for key,parts in states.items():
        cursor=0;valid=bool(parts);total=None
        for span,state in sorted(parts,key=lambda p:p[0]['start']):
            valid=valid and span['start']==cursor and state=='succeeded'
            total=span['total'];cursor=span['end']
        valid=valid and cursor==total
        if valid:processed.append(key)
        elif any(state=='failed' for _,state in parts):failed.append(key)
        else:pending.append(key)
    complete=not failed and not pending and bool(rows) and all(r['state']=='succeeded' for r in rows)
    return Coverage(sorted(processed),sorted(failed),sorted(pending),complete)
