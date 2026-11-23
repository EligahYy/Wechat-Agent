"""Resolve all scoped identities before applying any batch updates."""
from collections import Counter
import hashlib
import json
from uuid import uuid4


def save_shipments(conn,key,candidates,restore=None):
    issues=[];saved=[];plans=[]
    def fingerprint(candidate):return hashlib.sha256(json.dumps(sorted({ref.message_id for ref in candidate.sources})).encode()).hexdigest()
    counts=Counter(fingerprint(candidate) for candidate in candidates)
    for candidate in candidates:
        anchor=fingerprint(candidate)
        if counts[anchor]>1:
            issues.append('shipment_match_ambiguous:'+candidate.candidate_key);continue
        mapped=conn.execute('SELECT shipment_id FROM shipment_keys WHERE account_id=? AND contact_id=? AND candidate_key=?',(key.account_id,key.contact_id,candidate.candidate_key)).fetchone()
        anchored=conn.execute('SELECT shipment_id FROM shipment_anchors WHERE account_id=? AND contact_id=? AND anchor=?',(key.account_id,key.contact_id,anchor)).fetchone()
        identities={row[0] for row in (mapped,anchored) if row}
        if candidate.existing_id:identities.add(candidate.existing_id)
        if len(identities)>1:
            issues.append('shipment_match_conflict:'+candidate.candidate_key);continue
        identifier=next(iter(identities),str(uuid4()))
        old=conn.execute('SELECT * FROM shipments WHERE account_id=? AND shipment_id=?',(key.account_id,identifier)).fetchone()
        if old and old['contact_id']!=key.contact_id:
            issues.append('shipment_outside_contact');continue
        plans.append((identifier,anchor,old,candidate))
    targets=Counter(plan[0] for plan in plans)
    for identifier,anchor,old,candidate in plans:
        if targets[identifier]>1:
            issues.append('shipment_target_conflict:'+candidate.candidate_key);continue
        if old and restore:
            candidate = restore(old['payload_json'], candidate)
            if candidate is None:
                continue
        candidate=candidate.model_copy(update={'existing_id':identifier})
        # Model reruns never overwrite the separately editable human numbers.
        conn.execute('''INSERT INTO shipments(account_id,contact_id,shipment_id,stage,payload_json,numbers_json)
            VALUES(?,?,?,?,?,?) ON CONFLICT(account_id,shipment_id) DO UPDATE SET version=shipments.version+CASE WHEN shipments.stage!=excluded.stage OR shipments.payload_json!=excluded.payload_json THEN 1 ELSE 0 END,stage=excluded.stage,payload_json=excluded.payload_json''',
            (key.account_id,key.contact_id,identifier,candidate.stage,candidate.model_dump_json(),json.dumps(candidate.numbers,ensure_ascii=False)))
        conn.execute('INSERT INTO shipment_keys VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(key.account_id,key.contact_id,candidate.candidate_key,identifier))
        conn.execute('INSERT INTO shipment_anchors VALUES(?,?,?,?) ON CONFLICT DO NOTHING',(key.account_id,key.contact_id,anchor,identifier))
        saved.append(candidate)
    return saved,issues
