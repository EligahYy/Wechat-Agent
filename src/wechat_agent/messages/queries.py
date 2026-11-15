"""Author-indexed browse scopes; membership alone never proves group speech."""
from ..operations.service import OperationError
from ..contacts.names import present_source_title

ORDER='julianday(m.sent_at)'


def timeline_sources(conn,account_id,contact_id,conversation_id=None):
    contact=conn.execute("SELECT 1 FROM contacts WHERE account_id=? AND contact_id=? AND is_self=0 AND identity_state='active'",(account_id,contact_id)).fetchone()
    if contact is None:raise OperationError('messages_not_found',404)
    # Start with the author's rows, not one correlated search for every group.
    groups=conn.execute("""SELECT DISTINCT v.conversation_id,v.kind,v.title FROM messages m
        JOIN conversations v ON v.account_id=m.account_id AND v.conversation_id=m.conversation_id
        WHERE m.account_id=? AND m.sender_id=? AND m.kind NOT IN ('system','revoke')
        AND v.kind='group'""",(account_id,contact_id)).fetchall()
    # The candidate set is the peer's private relationships, usually very small.
    # All self identities count as our side, including an ID unlike account_id.
    private=conn.execute("""SELECT v.conversation_id,v.kind,v.title FROM members peer
        JOIN conversations v ON v.account_id=peer.account_id AND v.conversation_id=peer.conversation_id
        WHERE peer.account_id=? AND peer.contact_id=? AND v.kind='private'
        AND EXISTS(SELECT 1 FROM messages actual WHERE actual.account_id=v.account_id AND actual.conversation_id=v.conversation_id AND actual.kind NOT IN ('system','revoke'))
        AND NOT EXISTS(SELECT 1 FROM members other JOIN contacts person ON person.account_id=other.account_id AND person.contact_id=other.contact_id WHERE other.account_id=v.account_id AND other.conversation_id=v.conversation_id AND other.contact_id NOT IN (?,?) AND person.is_self=0)
        AND NOT EXISTS(SELECT 1 FROM messages other WHERE other.account_id=v.account_id AND other.conversation_id=v.conversation_id AND other.kind NOT IN ('system','revoke') AND (other.sender_id IS NULL OR (other.sender_id NOT IN (?,?) AND NOT EXISTS(SELECT 1 FROM contacts person WHERE person.account_id=other.account_id AND person.contact_id=other.sender_id AND person.is_self=1))))
        """,(account_id,contact_id,contact_id,account_id,contact_id,account_id)).fetchall()
    sources=sorted((dict(row) for row in [*groups,*private]),key=lambda row:(row['kind'],row['conversation_id']))
    for source in sources:source['title']=present_source_title(source['title'],source['conversation_id'])
    if conversation_id is not None and conversation_id not in {row['conversation_id'] for row in sources}:raise OperationError('messages_not_found',404)
    return sources


def message_scope(conn,account,contact,*,sources,conversation_id=None,bounds=None):
    """Resolve eligible rooms once, then reuse simple indexed predicates per read."""
    rooms={row['conversation_id'] for row in sources}
    if bounds:
        authored={row[0] for row in conn.execute("""SELECT DISTINCT conversation_id FROM messages
            WHERE account_id=? AND sender_id=? AND kind NOT IN ('system','revoke')
            AND julianday(sent_at)>=julianday(?) AND julianday(sent_at)<julianday(?)""",(account,contact,*bounds))}
        rooms&=authored|{row['conversation_id'] for row in sources if row['kind']=='private'}
    if conversation_id is not None:rooms&={conversation_id}
    where="m.account_id=? AND m.kind NOT IN ('system','revoke') AND julianday(m.sent_at) IS NOT NULL"
    params=[account]
    if rooms:
        where+=' AND m.conversation_id IN ('+','.join('?' for _ in rooms)+')';params.extend(sorted(rooms))
    else:where+=' AND 0'
    if bounds:
        where+=' AND julianday(m.sent_at)>=julianday(?) AND julianday(m.sent_at)<julianday(?)';params.extend(bounds)
    return where,params
