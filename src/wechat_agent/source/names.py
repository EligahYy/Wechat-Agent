"""Store scoped source-name evidence without inventing unobserved contacts."""
from datetime import datetime, timezone

from ..identities import is_person_identifier


def start_metadata(conn, account_id):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute('UPDATE contacts SET metadata_current=0 WHERE account_id=?', (account_id,))
    conn.execute('UPDATE contact_names SET current=0 WHERE account_id=?', (account_id,))
    conn.execute('UPDATE source_group_members SET current=0 WHERE account_id=?', (account_id,))
    return now


def archive_room_names(conn, account_id, room, now):
    if room.kind == 'group' and room.membership_state == 'unreadable':
        conn.execute('''UPDATE contact_names SET state='unreadable',current=1,observed_at=?
                        WHERE account_id=? AND conversation_id=? AND origin='group_member' ''',
                     (now, account_id, room.conversation_id))
    if room.kind == 'group' and room.membership_state == 'known':
        for identifier in room.member_ids:
            if is_person_identifier(identifier):
                conn.execute('''INSERT INTO source_group_members(account_id,conversation_id,contact_id,observed_at)
                    VALUES(?,?,?,?) ON CONFLICT(account_id,conversation_id,contact_id)
                    DO UPDATE SET current=1,observed_at=excluded.observed_at''',
                    (account_id, room.conversation_id, identifier, now))
    for name in room.name_evidence:
        conn.execute('''INSERT INTO contact_names(account_id,contact_id,origin,conversation_id,value,state,observed_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,contact_id,origin,conversation_id) DO UPDATE SET
            value=CASE WHEN excluded.state IN ('known','empty') THEN excluded.value ELSE contact_names.value END,
            state=excluded.state,observed_at=excluded.observed_at,current=1''',
            (account_id, name.contact_id, name.origin, name.conversation_id, name.value, name.state,
             name.observed_at.isoformat() if name.observed_at else now))


def finish_metadata(conn, account_id, people, rooms, metadata, now):
    info = metadata or {}
    errors = sum(getattr(person, field + '_state') == 'unreadable'
                 for person in people for field in ('remark', 'nickname')) + sum(room.title_state == 'unreadable' for room in rooms)
    conn.execute('''INSERT INTO source_metadata_status(account_id,observed_at,source_mode,patch_id,source_version,
        generation,resolver_generation,source_refreshed_at,people_seen,name_read_errors,groups_unreadable)
        VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
        observed_at=excluded.observed_at,source_mode=excluded.source_mode,patch_id=excluded.patch_id,
        source_version=excluded.source_version,generation=excluded.generation,
        resolver_generation=excluded.resolver_generation,source_refreshed_at=excluded.source_refreshed_at,
        people_seen=excluded.people_seen,name_read_errors=excluded.name_read_errors,groups_unreadable=excluded.groups_unreadable''',
        (account_id, now, info.get('mode', 'unknown'), info.get('patch_id'), info.get('source_version'),
         info.get('generation'), info.get('resolver_generation'), info.get('refreshed_at'),
         sum(not p.is_self for p in people), errors, sum(r.membership_state == 'unreadable' for r in rooms)))
