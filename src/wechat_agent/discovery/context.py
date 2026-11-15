"""Freeze a target's recent authored group material and adjacent context."""
from datetime import timedelta,timezone
import json
from uuid import uuid4
from .contracts import DiscoverySnapshot
from ..contacts.activity import derive_activity,instant
from ..source.contracts import ContactKey
from ..source.repository import transaction
from ..profiles.contracts import SourceRef

def build_discovery_snapshot(conn,key,cutoff,*,versions):
    key=ContactKey.model_validate(key)
    if cutoff.utcoffset() is None:raise ValueError('snapshot_cutoff_timezone_required')
    if not versions.get('model_config'):raise ValueError('model_config_version_required')
    cutoff=cutoff.astimezone(timezone.utc);start=cutoff-timedelta(days=90)
    with transaction(conn):
        people,activity,generation=derive_activity(conn,key.account_id)
        person=people.get(key.contact_id)
        if person is None or person['is_self'] or person['identity_state']!='active':raise ValueError('discovery_person_required')
        own={row['message_id'] for row in activity.get(key.contact_id,{}).get('group',[]) if start<=instant(row['sent_at'])<=cutoff}
        messages=[dict(row) for row in conn.execute('''SELECT m.message_id,m.revision,m.conversation_id,m.sender_id,m.sent_at,m.kind,m.body,m.reply_to
            FROM messages m JOIN conversations v ON v.account_id=m.account_id AND v.conversation_id=m.conversation_id
            WHERE m.account_id=? AND v.kind='group' ''',(key.account_id,)) if instant(row['sent_at']) is not None and start<=instant(row['sent_at'])<=cutoff]
        messages.sort(key=lambda row:(row['conversation_id'],instant(row['sent_at']),row['message_id']))
        indices=set()
        for index,row in enumerate(messages):
            if row['message_id'] not in own:continue
            for neighbor in range(max(0,index-2),min(len(messages),index+3)):
                if messages[neighbor]['conversation_id']==row['conversation_id']:indices.add(neighbor)
        material=[messages[index] for index in sorted(indices)]
        gaps=set()
        # References can be far from the local neighborhood or predate the window.
        # Keep exact same-room, prior messages; missing/cyclic-invalid refs stay gaps.
        available={row['message_id']:dict(row) for row in conn.execute('SELECT message_id,revision,conversation_id,sender_id,sent_at,kind,body,reply_to FROM messages WHERE account_id=?',(key.account_id,))}
        included={row['message_id'] for row in material}
        position=0
        while position<len(material):
            row=material[position];position+=1
            if not row['reply_to']:continue
            original=available.get(row['reply_to'])
            stamp=instant(original['sent_at']) if original else None
            if not original or original['conversation_id']!=row['conversation_id'] or stamp is None or stamp>instant(row['sent_at']):
                gaps.add('reply_unavailable:'+row['message_id']);continue
            if original['message_id'] not in included:
                material.append(original);included.add(original['message_id'])
        material.sort(key=lambda row:(row['conversation_id'],instant(row['sent_at']),row['message_id']))
        rooms={row['conversation_id'] for row in material}
        for room in rooms:
            cursor=conn.execute('SELECT complete,gaps_json FROM sync_cursors WHERE account_id=? AND conversation_id=?',(key.account_id,room)).fetchone()
            if not cursor or not cursor['complete'] or json.loads(cursor['gaps_json']):gaps.add('source_coverage_incomplete')
            if conn.execute('SELECT 1 FROM source_issues WHERE account_id=? AND conversation_id=? AND resolved=0',(key.account_id,room)).fetchone():gaps.add('source_issue_unresolved')
        for row in material:
            if row['kind']!='text':gaps.add('nontext_not_interpreted')
            if conn.execute('SELECT 1 FROM attachments WHERE account_id=? AND message_id=?',(key.account_id,row['message_id'])).fetchone():gaps.add('attachment_not_interpreted')
        if not own:gaps.add('no_recent_group_speech')
        snapshot=DiscoverySnapshot(id=str(uuid4()),key=key,cutoff=cutoff,generation=generation,versions={**versions,'strategy':'discovery-v1'},
            material_refs=tuple(SourceRef(message_id=row['message_id'],revision=row['revision']) for row in material),gaps=tuple(sorted(gaps)))
        conn.execute('INSERT INTO snapshots(account_id,snapshot_id,contact_id,manifest_json,payload_json) VALUES(?,?,?,?,?)',
            (key.account_id,snapshot.id,key.contact_id,snapshot.model_dump_json(),json.dumps({'target_id':key.contact_id,'own_message_ids':sorted(own),'messages':material},ensure_ascii=False)))
    return snapshot
