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
    from .relevance import load_relevance
    relevance = load_relevance(conn, account, snapshot_id)
    if relevance is not None:
        classified = {entry.message_id: entry.revision for entry in relevance.entries}
        if classified != refs or len(classified) != len(relevance.entries):
            raise ValueError('relevance_coverage_incomplete')
        refs = {entry.message_id: entry.revision for entry in relevance.entries if entry.level == 'high'}
    materials=json.loads(saved['materials_json']) if saved['materials_json'] else {}
    authorized={k:v['revision'] for k,v in materials.items()}==refs
    states={key:[] for key in refs}
    rows=conn.execute('SELECT unit_id,phase,state,primary_json,superseded FROM history_run_units WHERE account_id=? AND snapshot_id=?',(account,snapshot_id)).fetchall()
    by_id={r['unit_id']:r for r in rows}
    edges={}
    for edge in conn.execute('SELECT parent_id,child_id FROM history_refinements WHERE account_id=? AND snapshot_id=?',(account,snapshot_id)):
        edges.setdefault(edge['parent_id'],[]).append(edge['child_id'])
    def valid_tree(key,path):
        if key in path or key not in by_id:return False
        row=by_id[key]
        if not row['superseded']:return True
        children=edges.get(key,[])
        return bool(children) and all(c in by_id and by_id[c]['phase']==row['phase'] for c in children) and all(valid_tree(c,path|{key}) for c in children)
    authorized=authorized and all(valid_tree(r['unit_id'],set()) for r in rows)
    rows=[r for r in rows if not r['superseded']]
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
