"""Account-wide activity derivation: authors and direct relationships, never group heat."""
from datetime import datetime,timezone
import hashlib
import json

def instant(value):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.utcoffset() is not None else None
    except (ValueError,OverflowError,TypeError,AttributeError):return None

def derive_activity(conn,account):
    people={row['contact_id']:dict(row) for row in conn.execute('SELECT * FROM contacts WHERE account_id=?',(account,))}
    self_ids={key for key,row in people.items() if row['is_self']}|{account}
    rooms={row['conversation_id']:row['kind'] for row in conn.execute('SELECT conversation_id,kind FROM conversations WHERE account_id=?',(account,))}
    members={}
    for row in conn.execute('SELECT conversation_id,contact_id FROM members WHERE account_id=?',(account,)):
        members.setdefault(row[0],set()).add(row[1])
    rows=[dict(row) for row in conn.execute("SELECT message_id,conversation_id,sender_id,sent_at,reply_to,revision,kind FROM messages WHERE account_id=?",(account,))]
    coverage=[tuple(row) for row in conn.execute('SELECT conversation_id,complete,gaps_json FROM sync_cursors WHERE account_id=? ORDER BY conversation_id',(account,))]
    issues=[tuple(row) for row in conn.execute('SELECT conversation_id,code,resolved FROM source_issues WHERE account_id=? ORDER BY conversation_id,code,resolved',(account,))]
    generation=hashlib.sha256(json.dumps([sorted((row['message_id'],row['revision']) for row in rows),sorted((room,sorted(ids)) for room,ids in members.items()),sorted(rooms.items()),coverage,issues,sorted(self_ids)],sort_keys=True).encode()).hexdigest()
    saved=conn.execute('SELECT generation FROM scope_activity_generation WHERE account_id=?',(account,)).fetchone()
    if saved and saved[0]==generation:
        return people,{row['contact_id']:json.loads(row['value_json']) for row in conn.execute('SELECT * FROM contact_activity WHERE account_id=?',(account,))},generation
    activity={key:{'private':[],'direct':[],'group':[]} for key in people}
    originals={row['message_id']:row for row in rows}
    for row in rows:
        if row['kind'] in ('system','revoke') or instant(row['sent_at']) is None:continue
        room=row['conversation_id'];sender=row['sender_id'];kind=rooms.get(room)
        evidence={'message_id':row['message_id'],'revision':row['revision'],'sent_at':row['sent_at'],'conversation_id':room}
        if kind=='private':
            peers=members.get(room,set())-self_ids
            if len(peers)==1 and sender in peers|self_ids:
                peer=next(iter(peers))
                if peer in activity:activity[peer]['private'].append(evidence)
        elif kind=='group':
            if sender in activity and sender not in self_ids:activity[sender]['group'].append(evidence)
            original=originals.get(row['reply_to'])
            if not original or original['conversation_id']!=room or original['kind'] in ('system','revoke'):continue
            target=original['sender_id']
            peer=target if sender in self_ids else sender if target in self_ids else None
            if peer in activity and peer not in self_ids:activity[peer]['direct'].append(evidence)
    return people,activity,generation

def refresh_activity(conn,account):
    people,activity,generation=derive_activity(conn,account)
    conn.execute('DELETE FROM contact_activity WHERE account_id=?',(account,))
    conn.executemany('INSERT INTO contact_activity(account_id,contact_id,generation,value_json) VALUES(?,?,?,?)',[(account,key,generation,json.dumps(value)) for key,value in activity.items()])
    conn.execute('INSERT INTO scope_activity_generation(account_id,generation) VALUES(?,?) ON CONFLICT(account_id) DO UPDATE SET generation=excluded.generation',(account,generation))
