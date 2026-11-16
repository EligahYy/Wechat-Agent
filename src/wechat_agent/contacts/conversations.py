"""Account-bound conversation relation shared by sync, context and gap summaries."""
CONTACT_CONVERSATIONS_SQL='''SELECT conversation_id FROM conversations WHERE account_id=? AND (
 (kind='private' AND conversation_id=?) OR conversation_id IN (
 SELECT conversation_id FROM members WHERE account_id=? AND contact_id=?) OR conversation_id IN (
 SELECT conversation_id FROM messages WHERE account_id=? AND sender_id=?))'''

def conversation_params(key):
    return (key.account_id,key.contact_id,key.account_id,key.contact_id,key.account_id,key.contact_id)

def resolve_contact_conversations(conn,key):
    return {r[0] for r in conn.execute(CONTACT_CONVERSATIONS_SQL,conversation_params(key))}
