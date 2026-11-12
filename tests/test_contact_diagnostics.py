"""Read-only comparisons locate missing names without exporting people or chats."""
from contextlib import closing
import json

import pytest

from tests.test_source_adapter import NativeServer, adapter
from wechat_agent.source.contracts import ContactKey, ContactRecord
from wechat_agent.source.repository import archive_metadata


@pytest.mark.asyncio
async def test_contact_diagnostic_compares_names_without_messages_or_writes(db):
    from wechat_agent.contacts.check import collect_contact_diagnostics
    archive_metadata(db, 'account-a', [ContactRecord(
        key=ContactKey(account_id='account-a', contact_id='merchant-a'),
        remark='archived old name', nickname=None, is_self=False)], [])
    before = db.total_changes
    server = NativeServer()
    server.patched = False
    async with adapter(server) as source:
        report = await collect_contact_diagnostics(source, db)
    assert report['comparison'] == {'shared': 1, 'source_only': 1, 'archive_only': 0, 'different_names': 1}
    assert report['source']['counts']['people'] == 2
    assert report['source']['metadata']['mode'] == 'unknown'
    assert report['source']['metadata']['refreshed_at'] is None
    assert 'source_metadata_provenance_unavailable' in report['gaps']
    assert db.total_changes == before
    assert all(r.method == 'GET' and not r.url.path.endswith('messages') for r in server.requests)
    for private in ['account-a', 'merchant-a', 'archived old name', 'Real room']:
        assert private not in json.dumps(report)


@pytest.mark.asyncio
async def test_contact_diagnostic_distinguishes_empty_rejected_and_valid_names(db):
    from wechat_agent.contacts.check import collect_contact_diagnostics
    server = NativeServer()
    server.patched = False
    server.people = [
        {'user_name': 'one', 'remark': '', 'nick_name': ''},
        {'user_name': 'two', 'remark': 'bad\ufffdname', 'nick_name': ''},
        {'user_name': 'three', 'remark': '', 'nick_name': '小林🧑‍💻'},
    ]
    async with adapter(server) as source:
        report = await collect_contact_diagnostics(source, db)
    counts = report['source']['counts']
    assert (counts['names_empty'], counts['names_rejected'], counts['names_valid']) == (1, 1, 1)
    assert report['source']['field_errors'] is None


@pytest.mark.asyncio
async def test_contact_diagnostic_never_reads_metadata_after_account_mismatch(db):
    from wechat_agent.contacts.check import collect_contact_diagnostics
    server = NativeServer()
    server.patched = False
    server.account = 'wrong-account'
    async with adapter(server) as source:
        report = await collect_contact_diagnostics(source, db)
    assert report['status'] == 'failed'
    assert report['comparison'] is None
    assert report['gaps'] == ['source_account_mismatch']
    assert [r.url.path for r in server.requests] == ['/api/v1/health']


@pytest.mark.parametrize('target', ['archive.sqlite3', 'archive.sqlite3-wal', 'archive.sqlite3-shm', 'source.json'])
def test_diagnostic_report_cannot_replace_database_or_config(tmp_path, monkeypatch, target):
    from wechat_agent.contacts.check import main
    monkeypatch.setenv('WECHAT_AGENT_DATA_DIR', str(tmp_path))
    config = tmp_path / 'source.json'
    config.write_text('{}')
    path = tmp_path / target
    path.write_text('do not change')
    with pytest.raises(SystemExit) as error:
        main(['--account', 'account-a', '--source-config', str(config), '--output', str(path)])
    assert error.value.code == 2
    assert path.read_text() == 'do not change'


@pytest.mark.asyncio
async def test_patched_diagnostic_reports_errors_and_last_successful_metadata(db):
    from wechat_agent.contacts.check import collect_contact_diagnostics
    archive_metadata(db, 'account-a', [ContactRecord(
        key=ContactKey(account_id='account-a',contact_id='merchant-a'),
        remark='old name',nickname=None,is_self=False)], [], metadata={
        'mode':'sqlcipher','generation':2,'resolver_generation':2,
        'patch_id':'wechat-agent.1','refreshed_at':'2026-11-12T00:00:00Z'})
    server = NativeServer()
    server.people[0]['remark'] = {'value':None,'state':'unreadable'}
    async with adapter(server) as source:
        report = await collect_contact_diagnostics(source,db)
    assert report['source']['field_errors']['remark'] == 1
    assert report['archive']['metadata']['generation'] == 2
    assert report['archive']['metadata']['observed_at']
    assert 'source_name_read_failed' in report['gaps']
    assert 'old name' not in json.dumps(report)
    assert 'account-a' not in json.dumps(report)
