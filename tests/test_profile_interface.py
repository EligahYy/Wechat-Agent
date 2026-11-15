from contextlib import closing
from tests.factories import seed_case
from tests.profile_seed import seed_profile
from wechat_agent.storage.db import open_existing_db

def ready(client):
    with closing(open_existing_db(client.app.state.database_path)) as db:
        seed_case(db);seed_profile(db)
    from tests.fakes.source import FakeSource
    client.app.state.services.source=FakeSource()

def test_profile_evidence_preserves_exact_revision_and_rejects_outside_source(client):
    ready(client)
    path='/api/contacts/merchant-a/profile/evidence'
    result=client.get(path,params={'account_id':'acct-1','message_id':'fixture:dm-a:1','revision':1})
    assert result.status_code==200
    assert '约12方' in result.json()['items'][0]['body']
    assert result.json()['items'][0]['sender_name']=='商家甲'
    for mid,rev in [('foreign',1),('fixture:dm-a:1',2)]:
        assert client.get(path,params={'account_id':'acct-1','message_id':mid,'revision':rev}).status_code==404
    assert client.get(path,params={'account_id':'foreign','message_id':'fixture:dm-a:1','revision':1}).status_code==404

def test_list_uses_real_effective_profile_summary_and_business_time(client):
    ready(client)
    data=client.get('/api/contacts',params={'account_id':'acct-1','q':'商家甲'}).json()['items'][0]
    assert data['profile_summary']['goods']=='约12方'
    assert data['profile_summary']['communication']=='义乌到德国，询问海运含税到门价'
    assert data['last_business_at']=='2026-11-11T18:00:00+08:00'
    assert data['profile_status']=='incomplete' and data['profile_updated_at']

def test_manual_business_time_drives_contact_sort_and_summary(client):
    ready(client)
    response=client.patch('/api/contacts/merchant-b/manual',json={'account_id':'acct-1','expected_version':0,'fields':{'communication.last_business_at':'2026-11-12T09:00:00+08:00','goods.category':'人工品类'}})
    assert response.status_code==200
    rows=client.get('/api/contacts',params={'account_id':'acct-1','q':'商家','role':'merchant'}).json()['items']
    assert rows[0]['key']['contact_id']=='merchant-b'
    assert rows[0]['profile_status']=='manual'
    assert rows[0]['profile_summary']['goods']=='人工品类'
