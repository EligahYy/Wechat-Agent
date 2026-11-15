"""Recheck author, material, manual precedence and cancellation before publishing."""
import json
from .contracts import DiscoverySnapshot,DiscoveryResult,DiscoveryPublishResult
from ..contacts.activity import derive_activity
from ..source.repository import transaction,cancellation_requested

def publish_discovery(conn,snapshot,result,cancellation=None):
    snapshot=DiscoverySnapshot.model_validate(snapshot)
    result=DiscoveryResult.model_validate(result)
    def state(value):return DiscoveryPublishResult(state=value)
    account=snapshot.key.account_id;contact=snapshot.key.contact_id
    with transaction(conn):
        if cancellation and cancellation_requested(conn,account,cancellation):return state('cancelled')
        saved=conn.execute('SELECT manifest_json,payload_json FROM snapshots WHERE account_id=? AND snapshot_id=? AND contact_id=?',(account,snapshot.id,contact)).fetchone()
        if not saved or DiscoverySnapshot.model_validate_json(saved['manifest_json'])!=snapshot or result.contact_id!=contact:return state('rejected')
        override=conn.execute('SELECT included FROM business_scope_overrides WHERE account_id=? AND contact_id=?',(account,contact)).fetchone()
        if override and not override[0]:return state('manual_excluded')
        people,_,generation=derive_activity(conn,account)
        person=people.get(contact)
        if not person or person['is_self'] or person['identity_state']!='active':return state('rejected')
        if generation!=snapshot.generation:return state('stale')
        payload=json.loads(saved['payload_json']);own=set(payload['own_message_ids'])
        material={row['message_id']:row for row in payload['messages']}
        if any(ref.message_id not in own or material[ref.message_id]['sender_id']!=contact or material[ref.message_id]['revision']!=ref.revision or ref.attachment_id or ref.locator for ref in result.sources):return state('rejected')
        conn.execute('''INSERT INTO business_signals(account_id,contact_id,generation,intent,sources_json,coverage_complete,observed_at,model_version)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_id,contact_id) DO UPDATE SET generation=excluded.generation,intent=excluded.intent,
            sources_json=excluded.sources_json,coverage_complete=excluded.coverage_complete,observed_at=excluded.observed_at,model_version=excluded.model_version''',
            (account,contact,generation,result.intent,json.dumps([ref.model_dump() for ref in result.sources]),int(not snapshot.gaps and not result.gaps),snapshot.cutoff.isoformat(),snapshot.versions['model_config']))
    return state('published')
