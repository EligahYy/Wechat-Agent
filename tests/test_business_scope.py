from datetime import datetime,timedelta,timezone
import pytest
from tests.factories import seed_case,make_message,make_page
from wechat_agent.source.contracts import ContactKey
from wechat_agent.source.repository import archive_page
NOW=datetime(2026,11,13,tzinfo=timezone.utc)
KEY=ContactKey(account_id='acct-1',contact_id='merchant-a')

def test_manual_exclusion_wins_over_roles_and_new_messages(db):
    from wechat_agent.contacts.scope import classify_scope,set_scope
    seed_case(db)
    assert classify_scope(db,KEY,NOW).included
    result=set_scope(db,[KEY],False,{'merchant-a':0})
    assert len(result.updated)==1
    archive_page(db,make_page([make_message(message_id='new',sent_at=NOW,body='备货需要报价')]))
    assert not classify_scope(db,KEY,NOW).included
    db.execute("UPDATE contacts SET role='platform' WHERE contact_id='merchant-a'");db.commit()
    assert not classify_scope(db,KEY,NOW).included
    set_scope(db,[KEY],True,{'merchant-a':1})
    assert classify_scope(db,KEY,NOW+timedelta(days=200)).included

def test_group_activity_does_not_make_other_members_active(db):
    from wechat_agent.contacts.scope import classify_scope
    seed_case(db)
    db.execute("UPDATE contacts SET role='unknown'");db.commit()
    archive_page(db,make_page([make_message(message_id='recent',sender_id='provider-p',sent_at=NOW)]))
    # Long after fixture activity, only the actual recent speaker qualifies.
    future=NOW+timedelta(days=100)
    archive_page(db,make_page([make_message(message_id='later',sender_id='provider-p',sent_at=future)]))
    assert not classify_scope(db,ContactKey(account_id='acct-1',contact_id='merchant-b'),future).included
    candidate=classify_scope(db,ContactKey(account_id='acct-1',contact_id='provider-p'),future)
    assert candidate.included and candidate.provisional

def test_private_and_explicit_reply_evidence_with_90day_boundary(db):
    from wechat_agent.contacts.scope import classify_scope
    seed_case(db);db.execute("UPDATE contacts SET role='unknown'");db.commit()
    archive_page(db,make_page([make_message(message_id='direct',conversation_id='dm-a',sender_id='self-1',sent_at=NOW)],conversation_id='dm-a',conversation_kind='private'))
    assert 'recent_private' in classify_scope(db,KEY,NOW+timedelta(days=90)).reasons
    assert not classify_scope(db,KEY,NOW+timedelta(days=90,microseconds=1)).included
    archive_page(db,make_page([make_message(message_id='question',sender_id='self-1',sent_at=NOW),make_message(message_id='reply',sender_id='provider-p',reply_to='question',sent_at=NOW)]))
    assert 'direct_interaction' in classify_scope(db,ContactKey(account_id='acct-1',contact_id='provider-p'),NOW).reasons

def test_scope_conflicts_and_mixed_accounts(db):
    from wechat_agent.contacts.scope import set_scope
    seed_case(db)
    set_scope(db,[KEY],False,{'merchant-a':0})
    other=ContactKey(account_id='acct-1',contact_id='merchant-b')
    result=set_scope(db,[KEY,other],True,{'merchant-a':0,'merchant-b':0})
    assert len(result.updated)==1 and result.failed[0].code=='scope_version_conflict'
    with pytest.raises(ValueError):set_scope(db,[KEY,ContactKey(account_id='other',contact_id='x')],False,{'merchant-a':1,'x':0})

def test_system_and_potential_private_sources_are_not_activity(db):
    from wechat_agent.contacts.scope import classify_scope
    seed_case(db);db.execute("UPDATE contacts SET role='unknown'");db.commit()
    archive_page(db,make_page([make_message(message_id='notice',sender_id=None,kind='system',sent_at=NOW+timedelta(days=200))]))
    assert not classify_scope(db,KEY,NOW+timedelta(days=200)).included

def test_business_and_all_counts_match_scope_and_search(db):
    from wechat_agent.contacts.service import list_contacts
    from wechat_agent.contacts.scope import set_scope
    seed_case(db)
    set_scope(db,[KEY],False,{'merchant-a':0})
    all_people=list_contacts(db,'acct-1',scope='all',q='商家甲')
    business=list_contacts(db,'acct-1',scope='business',q='商家甲')
    assert all_people['total']==1 and business['total']==0
    assert all_people['items'][0]['business_scope']['reasons']==['manual_exclude']
    assert business['role_counts']['all']==business['scope_totals']['business']==0
    assert all_people['scope_totals']['all']==1

def test_activity_refresh_and_revision_invalidation(db):
    from wechat_agent.contacts.activity import refresh_activity,derive_activity
    seed_case(db)
    refresh_activity(db,'acct-1');db.commit()
    before=derive_activity(db,'acct-1')[2]
    archive_page(db,make_page([make_message(message_id='later-activity',sender_id='provider-p',sent_at=NOW)]))
    people,activity,after=derive_activity(db,'acct-1')
    assert after!=before and any(item['message_id']=='later-activity' for item in activity['provider-p']['group'])
