"""Shared, evidence-backed conversation scope for display and calendar metadata."""
from ..operations.service import OperationError
from ..contacts.names import present_source_title

# Group membership is directory metadata, not proof of having spoken there.
# A private peer may have only incoming messages from our side; keep verified
# two-party conversations even without target-authored history.
ROOMS="""SELECT v.conversation_id FROM conversations v WHERE v.account_id=? AND (
 EXISTS(SELECT 1 FROM messages authored WHERE authored.account_id=v.account_id AND authored.conversation_id=v.conversation_id AND authored.sender_id=? AND authored.kind NOT IN ('system','revoke'))
 OR (v.kind='private' AND EXISTS(SELECT 1 FROM members peer WHERE peer.account_id=v.account_id AND peer.conversation_id=v.conversation_id AND peer.contact_id=?)
 AND EXISTS(SELECT 1 FROM messages actual WHERE actual.account_id=v.account_id AND actual.conversation_id=v.conversation_id AND actual.kind NOT IN ('system','revoke'))
 AND NOT EXISTS(SELECT 1 FROM members other JOIN contacts person ON person.account_id=other.account_id AND person.contact_id=other.contact_id WHERE other.account_id=v.account_id AND other.conversation_id=v.conversation_id AND other.contact_id NOT IN (?,?) AND person.is_self=0)
 AND NOT EXISTS(SELECT 1 FROM messages other WHERE other.account_id=v.account_id AND other.conversation_id=v.conversation_id AND other.kind NOT IN ('system','revoke') AND (other.sender_id IS NULL OR (other.sender_id NOT IN (?,?) AND NOT EXISTS(SELECT 1 FROM contacts person WHERE person.account_id=other.account_id AND person.contact_id=other.sender_id AND person.is_self=1)))))
)"""

def room_params(account,contact):return [account,contact,contact,contact,account,contact,account]

def message_scope(account,contact):
    return "m.account_id=? AND m.kind NOT IN ('system','revoke') AND m.conversation_id IN ("+ROOMS+")",[account,*room_params(account,contact)]

def timeline_sources(conn,account_id,contact_id,conversation_id=None):
    contact=conn.execute("SELECT 1 FROM contacts WHERE account_id=? AND contact_id=? AND is_self=0 AND identity_state='active'",(account_id,contact_id)).fetchone()
    if contact is None:raise OperationError('messages_not_found',404)
    sources=[dict(row) for row in conn.execute('SELECT conversation_id,kind,title FROM conversations WHERE account_id=? AND conversation_id IN ('+ROOMS+') ORDER BY kind,conversation_id',[account_id,*room_params(account_id,contact_id)])]
    for source in sources:source['title']=present_source_title(source['title'],source['conversation_id'])
    if conversation_id is not None and conversation_id not in {row['conversation_id'] for row in sources}:raise OperationError('messages_not_found',404)
    return sources
