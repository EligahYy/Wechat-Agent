"""Compare source metadata with the local archive; never sync messages or write data."""

import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from ..config import Settings
from ..identities import choose_name, is_person_identifier
from ..source.adapter import SourceError, WXCLIAdapter
from ..source.probe import SourceConfig
from ..storage.db import open_existing_db
from .names import metadata_status, identity_quality


def _summarize(rows):
    counts = {'people': 0, 'names_valid': 0, 'names_empty': 0, 'names_rejected': 0, 'quarantined': 0}
    names = {}
    for identifier, remark, nickname, quarantined in rows:
        if quarantined or not is_person_identifier(identifier):
            counts['quarantined'] += 1
            continue
        counts['people'] += 1
        name, _ = choose_name(remark, nickname, identifier)
        names[identifier] = name
        if name:
            counts['names_valid'] += 1
        elif any(isinstance(value, str) and value.strip() for value in (remark, nickname)):
            counts['names_rejected'] += 1
        else:
            counts['names_empty'] += 1
    return counts, names


def _archive(conn, account_id):
    if conn is None:
        return {'status': 'unavailable', 'counts': None}, None
    rows = conn.execute('''SELECT contact_id,remark,nickname,identity_state FROM contacts
                           WHERE account_id=? AND is_self=0''', (account_id,))
    counts, names = _summarize((row[0], row[1], row[2], row[3] == 'quarantined') for row in rows)
    status = metadata_status(conn, account_id)
    quality = identity_quality(conn, account_id) if status is not None else None
    return {'status': 'read', 'counts': counts, 'metadata': status, 'display_quality': quality}, names


async def collect_contact_diagnostics(source, conn=None):
    """Only health/contacts/conversations GETs; compare exact stable IDs internally."""
    archive, old_names = _archive(conn, source.account_id)
    report = {
        'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'status': 'pending', 'archive': archive, 'source': None, 'comparison': None, 'gaps': [],
    }
    checked = await source.check()
    if checked.status != 'passed':
        report.update(status='failed', gaps=checked.gaps)
        return report
    try:
        people = await source.contacts()
        rooms = await source.conversations()
    except SourceError as error:
        report.update(status='failed', gaps=[str(error)])
        return report
    counts, new_names = _summarize(
        (person.key.contact_id, person.remark, person.nickname, False)
        for person in people if not person.is_self
    )
    counts['conversations'] = len(rooms)
    # Old versions cannot distinguish an empty name from a silent decode failure.
    metadata = checked.facts.get('metadata') or {
        'mode': 'unknown', 'patch_id': None, 'generation': None,
        'resolver_generation': None, 'refreshed_at': None,
    }
    report['source'] = {
        'version': checked.facts.get('cli_version', '').split(' ')[0],
        'metadata': metadata, 'counts': counts, 'field_errors': None,

    }
    if metadata.get('patch_id'):
        errors = {field: sum(getattr(person, field + '_state') == 'unreadable' for person in people if not person.is_self)
                  for field in ('remark','nickname')}
        errors['group_rosters'] = sum(room.membership_state == 'unreadable' for room in rooms)
        report['source']['field_errors'] = errors
        counts['scoped_name_candidates'] = sum(len(room.name_evidence) for room in rooms)
        counts['group_rosters_known'] = sum(room.kind == 'group' and room.membership_state == 'known' for room in rooms)
        counts['group_rosters_unknown'] = sum(room.kind == 'group' and room.membership_state != 'known' for room in rooms)
        if errors['remark'] or errors['nickname']:
            report['gaps'].append('source_name_read_failed')
        if errors['group_rosters']:
            report['gaps'].append('source_group_members_unreadable')
        report['gaps'].extend(getattr(source, 'metadata_gaps', []))
    if old_names is not None:
        shared = new_names.keys() & old_names.keys()
        report['comparison'] = {
            'shared': len(shared), 'source_only': len(new_names.keys() - old_names.keys()),
            'archive_only': len(old_names.keys() - new_names.keys()),
            'different_names': sum(new_names[key] != old_names[key] for key in shared),
        }
    if metadata.get('patch_id') is None:
        report['gaps'].append('source_metadata_provenance_unavailable')
    if conn is None:
        report['gaps'].append('archive_unavailable')
    report['status'] = 'pending' if report['gaps'] else 'passed'
    return report


async def _run(config, settings):
    async with WXCLIAdapter(config) as source:
        try:
            conn = open_existing_db(settings.data_dir / 'archive.sqlite3', readonly=True)
        except sqlite3.Error:
            return await collect_contact_diagnostics(source)
        with closing(conn), conn:
            conn.execute('BEGIN')
            return await collect_contact_diagnostics(source, conn)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--source-config', type=Path)
    parser.add_argument('--source-url')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    settings = Settings.load()
    source_path = args.source_config or settings.source_config
    protected = [settings.data_dir / name for name in ('archive.sqlite3', 'archive.sqlite3-wal', 'archive.sqlite3-shm')]
    protected += [Path.cwd() / '.local/config' / name for name in ('source.json', 'model.json')]
    protected += [path for path in (source_path, settings.model_config) if path]
    if args.output and args.output.expanduser().resolve() in {path.expanduser().resolve() for path in protected}:
        parser.error('report_output_conflicts_with_input')
    try:
        values = json.loads(source_path.read_text()) if source_path else {}
        values['expected_account_id'] = args.account
        if args.source_url:
            values['base_url'] = args.source_url
        report = asyncio.run(_run(SourceConfig.model_validate(values), settings))
    except (OSError, ValueError, TypeError, sqlite3.Error, SourceError):
        report = {'schema_version': 1, 'status': 'failed', 'gaps': ['contact_diagnostic_failed']}
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        path = args.output.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return 1 if report['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
