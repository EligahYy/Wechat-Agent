"""Non-secret preferences, account bootstrap and explicit M1 capability boundaries."""

from contextlib import closing
import json

import pytest

from tests.factories import seed_case
from wechat_agent.storage.db import open_db


def seed(client):
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)


def test_bootstrap_empty_archive_does_not_make_up_an_account(client):
    result = client.get('/api/settings')
    assert result.status_code == 200
    assert result.json()['account_id'] is None
    assert result.json()['capabilities']['organize'] is False
    assert result.json()['capabilities']['scheduler'] is False
    assert result.json()['source']['state'] == 'not_checked'


def test_preferences_persist_with_normalized_time_and_explicit_version(client):
    seed(client)
    current = client.get('/api/settings').json()
    assert current['account_id'] == 'acct-1'
    assert current['preferences']['daily_time'] == '08:30'
    response = client.patch('/api/settings', json={
        'account_id':'acct-1', 'expected_version':current['version'],
        'preferences':{'daily_time':'9:05', 'daily_enabled':True, 'appearance':'dark'}})
    assert response.status_code == 200
    saved = client.get('/api/settings').json()
    assert saved['preferences'] == {'daily_time':'09:05','daily_enabled':True,'appearance':'dark','reduce_motion':False}
    assert saved['version'] == 1
    assert saved['timezone'] == 'Asia/Shanghai'
    with closing(open_db(client.app.state.database_path)) as conn:
        assert json.loads(conn.execute("SELECT value_json FROM settings WHERE name='preferences'").fetchone()[0])['daily_time']=='09:05'


@pytest.mark.parametrize('preferences', [{'daily_time':'24:00'},{'daily_time':'９:05'},{'appearance':'blue'},{'daily_enabled':'yes'}, {'api_key':'private-token'}])
def test_invalid_preferences_never_save_or_echo_input(client, preferences):
    seed(client)
    response=client.patch('/api/settings',json={'account_id':'acct-1','expected_version':0,'preferences':preferences})
    assert response.status_code==422
    assert 'private-token' not in response.text
    assert client.get('/api/settings').json()['version']==0


def test_preferences_reject_stale_version_and_foreign_account(client):
    seed(client)
    body={'account_id':'acct-1','expected_version':0,'preferences':{'appearance':'dark'}}
    assert client.patch('/api/settings',json=body).status_code==200
    assert client.patch('/api/settings',json=body).status_code==409
    assert client.get('/api/settings',params={'account_id':'foreign'}).status_code==403
    assert client.patch('/api/settings',json={**body,'account_id':'foreign'}).status_code==403


def test_status_reports_configuration_without_reading_network_or_exposing_secrets(client,tmp_path):
    from wechat_agent.config import Settings
    seed(client)
    model=tmp_path/'model.json'
    model.write_text(json.dumps({'model_id':'model-from-config','api_key':'private-token','base_url':'https://private.example'}))
    client.app.state.settings=Settings(data_dir=tmp_path,model_config=model)
    response=client.get('/api/settings')
    assert response.status_code==200
    assert response.json()['model']=={'state':'configured','model_id':'model-from-config'}
    assert response.json()['source']['state']=='not_checked'
    assert 'private-token' not in response.text
    assert 'private.example' not in response.text


def test_source_status_uses_last_operation_evidence_without_a_network_probe(client):
    import asyncio
    from tests.fakes.source import FakeSource
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.worker import run_next
    seed(client)
    source=FakeSource()
    client.app.state.services.source=source
    with closing(open_db(client.app.state.database_path)) as conn:
        create_operation(conn,'sync',OperationScope(account_id='acct-1'),'last-sync')
        asyncio.run(run_next(conn,client.app.state.services))
    previous=list(source.calls)
    result=client.get('/api/settings').json()
    assert result['source']['state']=='last_sync_succeeded'
    assert result['source']['last_sync_at']
    assert source.calls==previous
