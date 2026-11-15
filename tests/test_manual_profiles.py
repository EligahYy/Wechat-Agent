from contextlib import closing
import json
import pytest
from wechat_agent.storage.db import open_existing_db
from wechat_agent.source.contracts import ContactKey




def patch_manual(client,**data):
    return client.patch('/api/contacts/merchant-a/manual',json={'account_id':'acct-1','expected_version':0,**data})


def profile(client):
    return client.get('/api/contacts/merchant-a/profile',params={'account_id':'acct-1'})


def test_manual_numbers_do_not_ship(client,seeded_shipment):
    response=client.patch(f'/api/shipments/{seeded_shipment}/numbers',json={'account_id':'acct-1','contact_id':'merchant-a','numbers':['A-1','A-1'],'expected_version':1})
    assert response.status_code==200
    assert response.json()['numbers']==['A-1'] and response.json()['stage']=='询价'
    assert response.json()['origin']=='manual' and response.json()['version']==2


def test_manual_fixed_field_and_notes_have_no_fake_sources(client,seeded_shipment):
    response=patch_manual(client,fields={'goods.volume':'人工确认15方','communication.tags':['询价中']},notes={'goods':'需要拍照','logistics':'预约提货'})
    assert response.status_code==200 and response.json()['manual_version']==1
    data=profile(client).json()
    assert data['effective']['goods']['volume']['value']=='人工确认15方'
    assert data['effective']['goods']['volume']['origin']=='manual'
    assert data['effective']['goods']['volume']['sources']==[]
    assert data['manual']['notes']=={'goods':'需要拍照','logistics':'预约提货'}
    assert data['model'] is None and data['complete'] is False


def test_manual_version_conflict_cannot_overwrite_and_noop_does_not_increment(client,seeded_shipment):
    assert patch_manual(client,notes={'goods':'first'}).status_code==200
    response=patch_manual(client,notes={'goods':'stale'})
    assert response.status_code==409
    assert profile(client).json()['manual']['notes']['goods']=='first'
    assert patch_manual(client,expected_version=1,notes={'goods':'first'}).json()['manual_version']==1


@pytest.mark.parametrize('fields,notes',[
    ({'custom':'value'},{}),({'goods.volume':''},{}),({'goods.volume':12},{}),
    ({'communication.tags':['不存在']},{}),({'communication.tags':['询价中','暂无新需求记录']},{}),
    ({'communication.last_business_at':'2026-11-15'},{}),({}, {'other':'no'}),
])
def test_invalid_fixed_fields_rejected_before_writes(client,seeded_shipment,fields,notes):
    assert patch_manual(client,fields=fields,notes=notes).status_code==422
    assert profile(client).json()['manual_version']==0


@pytest.mark.parametrize('numbers',[[''],[' '],['X'*257],[12]])
def test_invalid_numbers_rejected(client,seeded_shipment,numbers):
    response=client.patch('/api/shipments/shipment-test/numbers',json={'account_id':'acct-1','contact_id':'merchant-a','numbers':numbers,'expected_version':1})
    assert response.status_code==422


def test_numbers_scoped_to_contact_and_account(client,seeded_shipment):
    for account,contact in [('acct-1','merchant-b'),('foreign','merchant-a')]:
        response=client.patch('/api/shipments/shipment-test/numbers',json={'account_id':account,'contact_id':contact,'numbers':['A'],'expected_version':1})
        assert response.status_code==404
    assert profile(client).json()['shipments'][0]['numbers']==[]


def test_numbers_conflict_and_clear_preserve_stage_and_history(client,seeded_shipment):
    body={'account_id':'acct-1','contact_id':'merchant-a','numbers':[' A ','B','A'],'expected_version':1}
    first=client.patch('/api/shipments/shipment-test/numbers',json=body)
    assert first.status_code==200 and first.json()['numbers']==['A','B']
    assert client.patch('/api/shipments/shipment-test/numbers',json=body).status_code==409
    assert client.patch('/api/shipments/shipment-test/numbers',json={**body,'numbers':[],'expected_version':2}).json()['stage']=='询价'
    assert profile(client).json()['manual_version']==2


def test_manual_persists_new_connection_and_keeps_event_audit(client,seeded_shipment):
    patch_manual(client,fields={'goods.volume':'15方'},notes={'goods':'note'})
    from wechat_agent.profiles.manual import read_profile
    with closing(open_existing_db(client.app.state.database_path,readonly=True)) as conn:
        data=read_profile(conn,ContactKey(account_id='acct-1',contact_id='merchant-a'))
        assert data['manual']['fields']['goods.volume']=='15方'
        assert conn.execute('SELECT COUNT(*) FROM profile_manual_events').fetchone()[0]==1


def test_model_rerun_keeps_human_override_and_clear_restores_model(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.profiles.manual import save_manual,read_profile
    from wechat_agent.context.builder import build_snapshot
    publish(db,snapshot,analysis_result,cancellation)
    assert save_manual(db,snapshot.key,{'fields':{'goods.volume':'15方'},'notes':{'goods':'补充'}},0)==1
    assert publish(db,snapshot,analysis_result,cancellation).reason=='manual_changed'
    newer=build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)
    assert publish(db,newer,analysis_result,cancellation).version==2
    data=read_profile(db,snapshot.key)
    assert data['effective']['goods']['volume']['value']=='15方'
    assert data['model']['goods']['volume']['value']=='约12方'
    assert data['pending'] is False
    assert save_manual(db,snapshot.key,{'fields':{'goods.volume':None},'notes':{'goods':''}},1)==2
    data=read_profile(db,snapshot.key)
    assert data['effective']['goods']['volume']['value']=='约12方'
    assert data['effective']['goods']['volume']['origin']=='model'
    assert data['manual']['notes']=={} and data['pending'] is True
    assert db.execute('SELECT COUNT(*) FROM profile_versions').fetchone()[0]==2


def test_numbers_block_late_publication_and_survive_model_batch_updates(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.profiles.manual import save_numbers,read_profile
    from wechat_agent.context.builder import build_snapshot
    from wechat_agent.profiles.contracts import ShipmentCandidate
    result=analysis_result.model_copy(deep=True)
    result.shipments=[ShipmentCandidate(candidate_key='numbers',stage='询价',sources=result.goods.volume.sources)]
    publish(db,snapshot,result,cancellation)
    batch=db.execute('SELECT * FROM shipments').fetchone()
    old=build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)
    save_numbers(db,snapshot.key,batch['shipment_id'],['HUMAN-01'],1)
    assert publish(db,old,result,cancellation).reason=='manual_changed'
    current=build_snapshot(db,snapshot.key,snapshot.cutoff,versions=snapshot.versions)
    result.shipments[0].existing_id=batch['shipment_id'];result.shipments[0].stage='已走货'
    assert publish(db,current,result,cancellation).version==2
    data=read_profile(db,snapshot.key)['shipments'][0]
    assert data['numbers']==['HUMAN-01'] and data['numbers_origin']=='manual'
    assert data['version']==3 and data['stage']=='已走货'


def test_manual_edit_rolls_back_when_audit_write_fails(client,seeded_shipment):
    with closing(open_existing_db(client.app.state.database_path)) as conn,conn:
        conn.execute("CREATE TRIGGER reject_manual_event BEFORE INSERT ON profile_manual_events BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    assert patch_manual(client,notes={'goods':'must rollback'}).status_code==503
    data=profile(client).json()
    assert data['manual_version']==0 and data['manual']['notes']=={}


def test_group_resource_is_not_a_profile(client,seeded_shipment):
    response=client.get('/api/contacts/fake@chatroom/profile',params={'account_id':'acct-1'})
    assert response.status_code==404


def test_manual_business_time_requires_iso_with_timezone(client,seeded_shipment):
    assert patch_manual(client,fields={'communication.last_business_at':'1700000000'}).status_code==422


def test_conflicting_model_fact_is_exposed_without_overriding_human(db,snapshot,analysis_result,cancellation):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.profiles.manual import save_manual,read_profile
    publish(db,snapshot,analysis_result,cancellation)
    save_manual(db,snapshot.key,{'fields':{'goods.volume':'15方'}},0)
    data=read_profile(db,snapshot.key)
    conflict=next(item for item in data['conflicts'] if item['path']=='goods.volume')
    assert conflict['model_value']=='约12方' and conflict['manual_value']=='15方'
    assert conflict['model_sources']==analysis_result.goods.volume.model_dump()['sources']
    assert data['effective']['goods']['volume']['value']=='15方'


def test_provider_historical_profile_is_readable_but_cannot_edit(client,seeded_shipment):
    patch_manual(client,notes={'goods':'retain'})
    with closing(open_existing_db(client.app.state.database_path)) as conn,conn:
        conn.execute("UPDATE contacts SET role='provider' WHERE contact_id='merchant-a'")
    data=profile(client).json()
    assert data['applicable'] is False and data['manual']['notes']['goods']=='retain'
    assert patch_manual(client,expected_version=1,notes={'goods':'no'}).status_code==404


def test_foreign_account_and_quarantined_profile_are_hidden(client,seeded_shipment):
    assert client.get('/api/contacts/merchant-a/profile',params={'account_id':'foreign'}).status_code==404
    with closing(open_existing_db(client.app.state.database_path)) as conn,conn:
        conn.execute("UPDATE contacts SET identity_state='quarantined' WHERE contact_id='merchant-a'")
    assert profile(client).status_code==404
    assert patch_manual(client,notes={'goods':'no'}).status_code==404


def test_empty_patch_rejected_and_notes_clear_is_noop_on_empty(client,seeded_shipment):
    assert patch_manual(client).status_code==422
    assert patch_manual(client,notes={'goods':''}).json()['manual_version']==0


@pytest.mark.parametrize('change',['append','revision','new-room'])
def test_profile_read_detects_new_archive_inputs(db,snapshot,analysis_result,cancellation,change):
    from wechat_agent.profiles.publisher import publish
    from wechat_agent.profiles.manual import read_profile
    from tests.factories import make_message,make_page
    from wechat_agent.source.repository import archive_page
    publish(db,snapshot,analysis_result,cancellation)
    assert not read_profile(db,snapshot.key)['pending']
    if change=='revision':
        record=make_message(message_id='fixture:group-1:1',body='后续修订',source_revision='v2')
    elif change=='new-room':
        record=make_message(message_id='new-room-input',conversation_id='new-room')
    else:record=make_message(message_id='after-profile')
    archive_page(db,make_page([record],conversation_id=record.conversation_id))
    assert read_profile(db,snapshot.key)['pending']
