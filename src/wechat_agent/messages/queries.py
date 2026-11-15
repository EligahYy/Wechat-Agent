from ..operations.service import OperationError
from ..contacts.names import present_source_title

def timeline_sources(conn,account_id,contact_id,conversation_id=None):
    contact=conn.execute("SELECT * FROM contacts WHERE account_id=? AND contact_id=? AND is_self=0 AND identity_state='active'",(account_id,contact_id)).fetchone()
    if contact is None:
        raise OperationError('messages_not_found',404)
    sources=[dict(row) for row in conn.execute('''SELECT v.conversation_id,v.kind,v.title FROM conversations v
        WHERE v.account_id=? AND (v.conversation_id IN (
            SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?) OR v.conversation_id IN (
            SELECT conversation_id FROM messages WHERE account_id=? AND sender_id=?)) ORDER BY v.kind,v.conversation_id''',
        (account_id,account_id,contact_id,account_id,contact_id))]
    for source in sources:
        source['title']=present_source_title(source['title'],source['conversation_id'])
    if conversation_id is not None and conversation_id not in {source['conversation_id'] for source in sources}:
        raise OperationError('messages_not_found',404)
    return sources
