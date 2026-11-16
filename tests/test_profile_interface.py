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


def publish_without_old_batch(client):
    from datetime import datetime,timezone
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.source.contracts import ContactKey
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.operations.service import create_operation
    from wechat_agent.operations.contracts import OperationScope,CancellationToken
    with closing(open_existing_db(client.app.state.database_path)) as db:
        snapshot=build_snapshot(db,ContactKey(account_id='acct-1',contact_id='merchant-a'),datetime.now(timezone.utc))
        op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'without-old-batch')
        candidate={'contact_id':'merchant-a','communication':{'summary':{'state':'known','value':'已发出','sources':[{'message_id':'fixture:group-1:1','revision':1}]}}}
        result=publish(db,snapshot,candidate,CancellationToken(operation_id=op.id,generation=op.generation))
        assert result.version==2,result


def test_retained_shipment_evidence_uses_its_published_snapshot_after_new_profile(client):
    ready(client);publish_without_old_batch(client)
    profile=client.get('/api/contacts/merchant-a/profile?account_id=acct-1').json()
    assert profile['model_version']==2 and len(profile['shipments'])==1
    ref=profile['shipments'][0]['details']['sources'][0]
    result=client.get('/api/contacts/merchant-a/profile/evidence',params={'account_id':'acct-1',**ref})
    assert result.status_code==200,result.text
    cited=next(row for row in result.json()['items'] if row['is_evidence'])
    assert cited['message_id']=='fixture:dm-a:1' and cited['revision']==1 and '约12方' in cited['body']
    for mid,revision in [('fixture:dm-a:2',1),('fixture:dm-a:1',2),('foreign',1)]:
        assert client.get('/api/contacts/merchant-a/profile/evidence',params={'account_id':'acct-1','message_id':mid,'revision':revision}).status_code==404


def test_retained_batch_evidence_stays_at_exact_old_revision_and_account(client):
    from tests.factories import make_page,make_message
    from wechat_agent.source.repository import archive_page
    ready(client)
    with closing(open_existing_db(client.app.state.database_path)) as db:
        archive_page(db,make_page([make_message(conversation_id='dm-a',message_id='fixture:dm-a:1',body='修订后的新说明')],conversation_id='dm-a',conversation_kind='private'))
    publish_without_old_batch(client)
    params={'account_id':'acct-1','message_id':'fixture:dm-a:1','revision':1}
    result=client.get('/api/contacts/merchant-a/profile/evidence',params=params)
    assert result.status_code==200,result.text
    target=next(row for row in result.json()['items'] if row['is_evidence'])
    assert target['revision']==1 and target['is_historical'] is True and '约12方' in target['body']
    assert client.get('/api/contacts/merchant-a/profile/evidence',params={**params,'account_id':'foreign'}).status_code==404
    assert client.get('/api/contacts/merchant-b/profile/evidence',params=params).status_code==404


def test_historical_reference_without_a_visible_current_fact_or_batch_is_not_readable(client):
    ready(client);publish_without_old_batch(client)
    with closing(open_existing_db(client.app.state.database_path)) as db,db:
        db.execute("DELETE FROM shipment_keys WHERE account_id='acct-1' AND contact_id='merchant-a'")
        db.execute("DELETE FROM shipment_anchors WHERE account_id='acct-1' AND contact_id='merchant-a'")
        db.execute("DELETE FROM shipments WHERE account_id='acct-1' AND contact_id='merchant-a'")
    assert client.get('/api/contacts/merchant-a/profile/evidence',params={'account_id':'acct-1','message_id':'fixture:dm-a:1','revision':1}).status_code==404
