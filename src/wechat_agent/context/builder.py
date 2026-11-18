"""Freeze one merchant's complete currently archived context in one transaction."""
from datetime import datetime,timezone
import json
from hashlib import sha256
from uuid import uuid4
from .contracts import ContextSnapshot,SnapshotError,ContextCoverage
from ..profiles.contracts import SourceRef
from ..profiles.manual import read_manual
from ..source.contracts import ContactKey
from ..source.repository import transaction
from ..source.coverage import NUMBERLESS_MESSAGE


def build_snapshot(conn,key:ContactKey,cutoff:datetime,*,versions:dict[str,str]|None=None,coverage:ContextCoverage|None=None,reuse_published:bool=False)->ContextSnapshot:
    key=ContactKey.model_validate(key)
    if not isinstance(cutoff,datetime) or cutoff.utcoffset() is None:raise ValueError('snapshot_cutoff_timezone_required')
    cutoff=cutoff.astimezone(timezone.utc)
    selected_versions={'template':'profile-v1','strategy':'workflow-v1','output_schema':'1','model_config':'unconfigured'}
    if versions is not None:
        if set(versions)!=set(selected_versions) or any(not isinstance(v,str) or not v.strip() for v in versions.values()):
            raise ValueError('snapshot_versions_required')
        selected_versions=dict(versions)
    account,contact=key.account_id,key.contact_id
    with transaction(conn):
        person=conn.execute("SELECT * FROM contacts WHERE account_id=? AND contact_id=? AND role='merchant' AND is_self=0 AND identity_state='active'",(account,contact)).fetchone()
        if person is None:raise SnapshotError('snapshot_merchant_required')
        from ..contacts.conversations import resolve_contact_conversations
        linked=resolve_contact_conversations(conn,key)
        rooms={room:dict(conn.execute('SELECT conversation_id,kind,title FROM conversations WHERE account_id=? AND conversation_id=?',(account,room)).fetchone()) for room in sorted(linked)}
        attachment_rows = {}
        material = []
        for room in sorted(linked):
            params = (account, room)
            if reuse_published:
                material.extend(tuple(row) for row in conn.execute(
                    'SELECT message_id,revision,sent_at,sender_id FROM messages WHERE account_id=? AND conversation_id=? ORDER BY message_id',
                    params,
                ))
            for attachment in conn.execute(
                """SELECT a.message_id,a.attachment_id,a.state,a.mime FROM attachments a JOIN messages m
                   ON a.account_id=m.account_id AND a.message_id=m.message_id
                   WHERE m.account_id=? AND m.conversation_id=? ORDER BY a.message_id,a.attachment_id""",
                params,
            ):
                attachment_rows.setdefault(attachment['message_id'], []).append({
                    key: attachment[key] for key in ('attachment_id', 'state', 'mime')
                })
        people={row['contact_id']:row for row in conn.execute('SELECT * FROM contacts WHERE account_id=?',(account,))}
        scope_version = conn.execute(
            'SELECT version FROM business_scope_overrides WHERE account_id=? AND contact_id=?', (account, contact)
        ).fetchone()
        head=conn.execute('SELECT version,manual_version FROM profile_heads WHERE account_id=? AND contact_id=?',(account,contact)).fetchone()
        manual = read_manual(conn, key)
        source = {}
        for room in rooms:
            cursor = conn.execute(
                'SELECT complete,gaps_json FROM sync_cursors WHERE account_id=? AND conversation_id=?', (account, room)
            ).fetchone()
            issues = sorted({row[0] for row in conn.execute(
                'SELECT DISTINCT code FROM source_issues WHERE account_id=? AND conversation_id=? AND resolved=0',
                (account, room),
            )})
            source[room] = (tuple(cursor) if cursor else None, issues)
        fingerprint = None
        if reuse_published:
            # A future-dated archived message can become visible without any
            # archive write. Until then use the full snapshot path.
            try:
                past = all(datetime.fromisoformat(row[2].replace('Z', '+00:00')) <= cutoff for row in material)
            except (TypeError, ValueError, OverflowError):
                past = False
            if past:
                actor_ids = {row[3] for row in material} | {contact}
                signature = [
                    rooms, material, attachment_rows, source, manual, selected_versions,
                    coverage.model_dump(mode='json') if coverage else None,
                    scope_version[0] if scope_version else 0, head[1] if head else 0,
                    sorted((identifier, *(person[name] for name in (
                        'role', 'role_version', 'identity_state', 'is_self', 'remark', 'nickname',
                        'remark_state', 'nickname_state',
                    ))) for identifier, person in people.items() if identifier in actor_ids),
                ]
                fingerprint = sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
                saved = conn.execute(
                    """SELECT s.manifest_json FROM profile_heads h JOIN profile_versions p
                       ON p.account_id=h.account_id AND p.contact_id=h.contact_id AND p.version=h.version
                       JOIN snapshots s ON s.account_id=p.account_id AND s.snapshot_id=p.snapshot_id
                       WHERE h.account_id=? AND h.contact_id=? AND s.material_fingerprint=?""",
                    (account, contact, fingerprint),
                ).fetchone()
                if saved:
                    return ContextSnapshot.model_validate_json(saved[0])
        rows=[]
        for room in sorted(linked):
            rows.extend(conn.execute('SELECT r.*,m.conversation_id FROM message_revisions r JOIN messages m ON r.account_id=m.account_id AND r.message_id=m.message_id AND r.revision=m.revision WHERE m.account_id=? AND m.conversation_id=?',(account,room)).fetchall())
        gaps={'history_complete_unverified'};messages=[];actors={}
        dated=[]
        for row in rows:
            try:
                stamp=datetime.fromisoformat(row['sent_at'].replace('Z','+00:00'))
                if stamp.utcoffset() is None:raise ValueError('naive')
                stamp=stamp.astimezone(timezone.utc)
            except (ValueError,OverflowError):
                gaps.add('message_time_invalid:'+row['message_id']);continue
            if stamp<=cutoff:dated.append((stamp,row['message_id'],row))
        rows=[item[2] for item in sorted(dated,key=lambda item:(item[0],item[1]))]
        for row in rows:
            sender=row['sender_id'];actor=people.get(sender)
            if sender is not None and (actor is None or actor['identity_state']!='active'):
                gaps.add('message_author_unverified:'+row['message_id'])
            elif actor is not None:
                # Names remain source metadata; never infer one from a person ID.
                name=actor['remark'] if actor['remark_state']=='known' else None
                name=name or (actor['nickname'] if actor['nickname_state']=='known' else None)
                actors[sender]={'contact_id':sender,'role':actor['role'],'role_version':actor['role_version'],
                    'is_self':bool(actor['is_self']),'name':name}
            attachments = attachment_rows.get(row['message_id'], [])
            gaps.update('attachment_not_processed:' + item['attachment_id'] for item in attachments)
            messages.append({field:row[field] for field in ('message_id','conversation_id','sender_id','sent_at','kind','body','reply_to','revision')})
            messages[-1].update(author_state='unassigned' if sender is None else 'active' if actor is not None and actor['identity_state']=='active' else 'unverified',attachments=attachments)
        ids={row['message_id'] for row in messages}
        for message in messages:
            if message['reply_to'] and message['reply_to'] not in ids:gaps.add('reply_unavailable:'+message['message_id'])
        for room in sorted(rooms):
            cursor, issues = source[room]
            cursor_gaps = set(json.loads(cursor[1])) if cursor else set()
            issue_codes = set(issues)
            known_partial = coverage and room in coverage.numberless_conversation_ids
            if known_partial and cursor and (cursor_gaps | issue_codes) == {NUMBERLESS_MESSAGE}:
                gaps.add(f'{NUMBERLESS_MESSAGE}:{room}')
                continue
            if cursor is None or not cursor[0]:
                gaps.add('source_not_complete:'+room)
            gaps.update(f'source_gap:{room}:{code}' for code in cursor_gaps)
            gaps.update(f'source_issue:{room}:{code}' for code in issue_codes)
        snapshot=ContextSnapshot(coverage=coverage,id=str(uuid4()),key=key,cutoff=cutoff,
            material_refs=tuple(SourceRef(message_id=row['message_id'],revision=row['revision']) for row in messages),
            role_version=person['role_version'],manual_version=head[1] if head else 0,profile_version=head[0] if head else 0,scope_version=scope_version[0] if scope_version else 0,versions=selected_versions,gaps=tuple(sorted(gaps)))
        payload={'messages':messages,'actors':actors,'conversations':rooms,'manual':manual}
        values = (account, snapshot.id, contact, snapshot.model_dump_json(),
                  json.dumps(payload, ensure_ascii=False, allow_nan=False))
        if fingerprint is None:
            conn.execute('INSERT INTO snapshots(account_id,snapshot_id,contact_id,manifest_json,payload_json) VALUES(?,?,?,?,?)',
                         values)
        else:
            conn.execute('INSERT INTO snapshots(account_id,snapshot_id,contact_id,manifest_json,payload_json,material_fingerprint) VALUES(?,?,?,?,?,?)',
                         (*values, fingerprint))
    return snapshot
