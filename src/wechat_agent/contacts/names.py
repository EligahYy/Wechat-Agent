"""Resolve display names separately from global names safe to copy to WeChat."""
from collections import defaultdict
from datetime import datetime
from ..identities import choose_name, usable_name


def present_source_title(value, identifier):
    if not isinstance(value, str):
        return None
    for suffix in (f' ({identifier})', f'（{identifier}）'):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return usable_name(value, identifier)


def load_catalog(conn, account_id, contact_ids=None):
    result = defaultdict(list)
    if contact_ids is not None and not contact_ids:
        return result
    scope = ' AND n.contact_id IN (' + ','.join('?' for _ in contact_ids) + ')' if contact_ids is not None else ''
    for row in conn.execute('''SELECT n.* FROM contact_names n JOIN contacts c
        ON c.account_id=n.account_id AND c.contact_id=n.contact_id
        WHERE n.account_id=? AND c.identity_state='active' ''' + scope, [account_id, *(contact_ids or [])]):
        result[row['contact_id']].append(dict(row))
    return result


def resolve_name(row, evidence):
    current = bool(row['metadata_current'])
    fresh_fields = [row[field] if current and row[field + '_state'] == 'known' else None
                    for field in ('remark', 'nickname')]
    name, origin = choose_name(*fresh_fields, row['contact_id'])
    reason = 'name_read_failed' if 'unreadable' in (row['remark_state'], row['nickname_state']) else 'source_name_state_unknown'
    scoped = [(item, usable_name(item['value'], row['contact_id'])) for item in evidence
              if item['current'] and item['state'] == 'known']
    scoped = [(item, value) for item, value in scoped if value]
    conflict = len({value for _, value in scoped}) > 1
    scope = None
    status = 'current'
    copy_name = name
    if not name and scoped:
        scoped.sort(key=lambda pair: (datetime.fromisoformat(pair[0]['observed_at']).timestamp(), pair[0]['origin'], pair[0]['conversation_id']), reverse=True)
        item, name = scoped[0]
        origin, scope, status = item['origin'], item['conversation_id'], 'scoped'
    if not name:
        name, origin = choose_name(row['remark'], row['nickname'], row['contact_id'])
        if name:
            status = 'last_known' if current else 'historical'
        else:
            historical = [(item, usable_name(item['value'], row['contact_id'])) for item in evidence
                          if item['state'] != 'empty']
            historical = [(item, value) for item, value in historical if value]
            if historical:
                historical.sort(key=lambda pair: datetime.fromisoformat(pair[0]['observed_at']).timestamp(), reverse=True)
                item, name = historical[0]
                origin, scope, status = item['origin'], item['conversation_id'], 'last_known'
                if item['state'] == 'unreadable':
                    reason = 'name_read_failed'
    if not name:
        status = 'missing'
        reason = 'source_name_empty' if current and row['remark_state'] == row['nickname_state'] == 'empty' else reason
    return {'display_name': name or '名称缺失', 'display_name_source': origin,
            'copy_name': copy_name, 'name_status': status, 'name_scope': scope,
            'name_conflict': conflict if status == 'scoped' else False,
            'name_reason': reason if status in ('last_known', 'missing') else None,
            'metadata_current': current, 'metadata_seen_at': row['metadata_seen_at']}


def match_contact_names(conn, account_id, query, catalog):
    """Match literal name text once; never search IDs, source titles or unused aliases."""
    needle = query.casefold()
    rowids, presentations = [], {}
    for row in conn.execute("""SELECT rowid AS search_rowid,* FROM contacts
        WHERE account_id=? AND is_self=0 AND identity_state='active' """, (account_id,)):
        presentation = resolve_name(row, catalog[row['contact_id']])
        presentations[row['contact_id']] = presentation
        names = [usable_name(row[field], row['contact_id']) for field in ('remark', 'nickname')
                 if row['metadata_current'] and row[field + '_state'] == 'known']
        if presentation['name_status'] != 'missing':
            names.append(presentation['display_name'])
        if any(needle in name.casefold() for name in names if name):
            rowids.append(row['search_rowid'])
    return rowids, presentations


def identity_quality(conn, account_id, catalog=None, presentations=None):
    catalog = load_catalog(conn, account_id) if catalog is None else catalog
    counts = {'quarantined': 0, 'names_unavailable': 0, 'names_scoped': 0,
              'names_historical': 0, 'name_read_errors': 0, 'not_in_contact_metadata': 0}
    for row in conn.execute('SELECT * FROM contacts WHERE account_id=? AND is_self=0', (account_id,)):
        if row['identity_state'] == 'quarantined':
            counts['quarantined'] += 1
            continue
        name = (presentations or {}).get(row['contact_id']) or resolve_name(row, catalog[row['contact_id']])
        counts['names_unavailable'] += name['name_status'] == 'missing'
        counts['names_scoped'] += name['name_status'] == 'scoped'
        counts['names_historical'] += name['name_status'] in ('historical', 'last_known')
        counts['name_read_errors'] += sum(row[field + '_state'] == 'unreadable' for field in ('remark', 'nickname'))
        counts['not_in_contact_metadata'] += not row['metadata_current']
    return counts


def metadata_status(conn, account_id):
    from datetime import datetime
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_metadata_status'").fetchone():
        return None
    row = conn.execute('SELECT * FROM source_metadata_status WHERE account_id=?', (account_id,)).fetchone()
    if row is None:
        return None
    def date(value):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed.isoformat() if parsed.utcoffset() is not None else None
        except (TypeError, ValueError):
            return None
    version = (row['source_version'] or '').split(' ')[0]
    return {
        'mode': row['source_mode'] if row['source_mode'] in ('sqlcipher','decrypted_cache') else 'unknown',
        'patch_id': 'wechat-agent.1' if row['patch_id'] == 'wechat-agent.1' else None,
        'source_version': version if version in ('0.7.4','0.7.4+wechat-agent.1') else None,
        'observed_at': date(row['observed_at']), 'refreshed_at': date(row['source_refreshed_at']),
        **{field: row[field] if type(row[field]) is int and row[field] >= 0 else None
           for field in ('generation','resolver_generation','people_seen','name_read_errors','groups_unreadable')},
    }
