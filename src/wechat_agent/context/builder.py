"""Freeze one merchant's complete currently archived context in one transaction."""
from datetime import datetime,timezone
import json
from uuid import uuid4
from .contracts import ContextSnapshot,SnapshotError
from ..profiles.contracts import SourceRef
from ..source.contracts import ContactKey
from ..source.repository import transaction


def build_snapshot(conn,key:ContactKey,cutoff:datetime,*,versions:dict[str,str]|None=None)->ContextSnapshot:
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
        rooms={row['conversation_id']:dict(row) for row in conn.execute('''SELECT conversation_id,kind,title FROM conversations WHERE account_id=? AND (
            conversation_id IN (SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?) OR
            conversation_id IN (SELECT conversation_id FROM messages WHERE account_id=? AND sender_id=?))''',(account,account,contact,account,contact))}
        rows=conn.execute('''SELECT r.*,m.conversation_id FROM message_revisions r JOIN messages m
            ON r.account_id=m.account_id AND r.message_id=m.message_id AND r.revision=m.revision
            WHERE m.account_id=? AND (m.sender_id=? OR m.conversation_id IN (
                SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?))
            ORDER BY r.message_id''',
            (account,contact,account,contact)).fetchall()
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
        people={row['contact_id']:row for row in conn.execute('SELECT * FROM contacts WHERE account_id=?',(account,))}
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
            attachments=[]
            for attachment in conn.execute('SELECT attachment_id,state,mime FROM attachments WHERE account_id=? AND message_id=? ORDER BY attachment_id',(account,row['message_id'])):
                attachments.append(dict(attachment))
                # Available bytes do not prove parsed/vision material coverage.
                gaps.add('attachment_not_processed:'+attachment['attachment_id'])
            messages.append({field:row[field] for field in ('message_id','conversation_id','sender_id','sent_at','kind','body','reply_to','revision')})
            messages[-1].update(author_state='unassigned' if sender is None else 'active' if actor is not None and actor['identity_state']=='active' else 'unverified',attachments=attachments)
        ids={row['message_id'] for row in messages}
        for message in messages:
            if message['reply_to'] and message['reply_to'] not in ids:gaps.add('reply_unavailable:'+message['message_id'])
        for room in sorted(rooms):
            cursor=conn.execute('SELECT complete,gaps_json FROM sync_cursors WHERE account_id=? AND conversation_id=?',(account,room)).fetchone()
            if cursor is None or not cursor['complete']:gaps.add('source_not_complete:'+room)
            if cursor:
                for gap in json.loads(cursor['gaps_json']):gaps.add('source_gap:'+room+':'+gap)
            for issue in conn.execute('SELECT DISTINCT code FROM source_issues WHERE account_id=? AND conversation_id=? AND resolved=0',(account,room)):
                gaps.add('source_issue:'+room+':'+issue['code'])
        snapshot=ContextSnapshot(id=str(uuid4()),key=key,cutoff=cutoff,
            material_refs=tuple(SourceRef(message_id=row['message_id'],revision=row['revision']) for row in messages),
            role_version=person['role_version'],manual_version=0,versions=selected_versions,gaps=tuple(sorted(gaps)))
        payload={'messages':messages,'actors':actors,'conversations':rooms}
        conn.execute('INSERT INTO snapshots(account_id,snapshot_id,contact_id,manifest_json,payload_json) VALUES(?,?,?,?,?)',
            (account,snapshot.id,contact,snapshot.model_dump_json(),json.dumps(payload,ensure_ascii=False,allow_nan=False)))
    return snapshot
