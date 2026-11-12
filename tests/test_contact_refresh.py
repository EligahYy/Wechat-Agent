"""Metadata-only operations must preserve messages, identities and cancellation fences."""
import asyncio
from contextlib import closing

import pytest

from tests.factories import seed_case
from tests.fakes.source import FakeSource
from wechat_agent.contacts.service import list_contacts
from wechat_agent.operations.contracts import OperationScope
from wechat_agent.operations.service import create_operation, control_operation
from wechat_agent.operations.worker import run_next
from wechat_agent.services import Services
from wechat_agent.source.contracts import ContactRecord


class MetadataSource(FakeSource):
    def __init__(self):
        super().__init__()
        self.refreshes = 0
        self.unreadable = False

    async def refresh_metadata(self):
        self.refreshes += 1
        for index, person in enumerate(self.people):
            if person.key.contact_id == 'merchant-a':
                self.people[index] = ContactRecord(key=person.key,is_self=False,
                    remark=None if self.unreadable else '更新后的名称',nickname=None,
                    remark_state='unreadable' if self.unreadable else 'known',
                    nickname_state='unreadable' if self.unreadable else 'empty')

    async def messages(self, *args):
        raise AssertionError('metadata refresh must not read messages')


def intent(db, key='refresh'):
    return create_operation(db,'refresh_contacts',OperationScope(account_id='acct-1'),key)


@pytest.mark.asyncio
async def test_refresh_is_idempotent_and_never_reads_messages_or_plans_analysis(db):
    seed_case(db)
    original = [tuple(row) for row in db.execute('SELECT message_id,sender_id,body,revision FROM messages ORDER BY message_id')]
    role = tuple(db.execute("SELECT role,role_version FROM contacts WHERE contact_id='merchant-a'").fetchone())
    first = intent(db)
    assert intent(db).id == first.id
    source = MetadataSource()
    result = await run_next(db,Services(source=source))
    assert result.state == result.source_state == 'succeeded'
    assert source.refreshes == 1
    assert result.counts['pages_processed'] == result.counts['analysis_required'] == 0
    assert result.counts['metadata_people'] > 0
    assert list_contacts(db,'acct-1',q='更新后的名称')['items'][0]['copy_name'] == '更新后的名称'
    assert original == [tuple(row) for row in db.execute('SELECT message_id,sender_id,body,revision FROM messages ORDER BY message_id')]
    assert tuple(db.execute("SELECT role,role_version FROM contacts WHERE contact_id='merchant-a'").fetchone()) == role


@pytest.mark.asyncio
async def test_unreadable_names_report_partial_refresh_and_keep_old_name(db):
    seed_case(db)
    intent(db)
    source = MetadataSource(); source.unreadable = True
    result = await run_next(db,Services(source=source))
    assert result.state == 'failed'
    assert 'source_name_read_failed' in result.items[0].gaps
    item = list_contacts(db,'acct-1',q='商家甲')['items'][0]
    assert item['display_name'] == '商家甲'
    assert item['name_status'] == 'last_known' and item['copy_name'] is None


@pytest.mark.asyncio
async def test_stop_while_metadata_is_in_flight_does_not_commit_late_names(db):
    seed_case(db)
    job = intent(db)
    entered, release = asyncio.Event(), asyncio.Event()
    class Waiting(MetadataSource):
        async def contacts(self):
            entered.set(); await release.wait()
            return self.people
    source = Waiting()
    running = asyncio.create_task(run_next(db,Services(source=source)))
    await entered.wait()
    control_operation(db,'acct-1',job.id,'stop')
    release.set()
    result = await running
    assert result.state == 'stopped'
    assert list_contacts(db,'acct-1',q='商家甲')['items'][0]['copy_name'] == '商家甲'
    assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 4


@pytest.mark.asyncio
async def test_metadata_scope_must_be_the_account(db):
    from wechat_agent.operations.service import OperationError
    seed_case(db)
    with pytest.raises(OperationError,match='metadata_refresh_account_scope_required'):
        create_operation(db,'refresh_contacts',OperationScope(account_id='acct-1',contact_id='merchant-a'),'wrong')


def test_refresh_intent_is_fast_and_settings_do_not_claim_messages_synced(client):
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn:
        seed_case(conn)
    response = client.post('/api/operations',json={'action':'refresh_contacts','scope':{'account_id':'acct-1'},'idempotency_key':'http-refresh'})
    assert response.status_code == 202
    assert response.json()['state'] == 'queued'
    with closing(open_db(client.app.state.database_path)) as conn:
        result = asyncio.run(run_next(conn,Services(source=MetadataSource())))
    assert result.state == 'succeeded'
    assert client.get('/api/settings').json()['source']['state'] == 'last_metadata_succeeded'

@pytest.mark.asyncio
@pytest.mark.parametrize("include_invalid",[False,True])
async def test_refresh_distinguishes_source_rows_from_archived_people_and_roles(db,include_invalid):
    from wechat_agent.source.contracts import ContactKey, ConversationRecord
    from wechat_agent.source.repository import archive_metadata
    def person(identifier, name=None, *, account='acct-1'):
        return ContactRecord(key=ContactKey(account_id=account,contact_id=identifier),remark=name,nickname=None,is_self=identifier==account)
    archive_metadata(db,'acct-1',[person('acct-1'),person('merchant-a','旧名'),person('historical','历史名称'),person('invalid\nidentifier','异常')],[])
    archive_metadata(db,'another-account',[person('other','其他账号',account='another-account')],[])
    source=MetadataSource()
    source.people=[person('acct-1'),person('merchant-a','本次名称'),person('current-no-name')]
    if include_invalid:
        source.people.append(person('invalid\nnew','隔离记录'))
    source.rooms=[ConversationRecord(account_id='acct-1',conversation_id='observed-only',kind='private',title=None,member_ids=['acct-1','observed-only'])]
    intent(db)
    result=await run_next(db,Services(source=source))
    listing=list_contacts(db,'acct-1')
    counts=result.counts
    assert counts['metadata_people']==2+include_invalid
    assert counts['contacts_current']==2
    assert counts['contacts_retained']==2
    assert counts['contacts_total']==listing['total']==listing['role_counts']['all']==4
    assert counts['contacts_total']==counts['contacts_current']+counts['contacts_retained']
    assert sum(listing['role_counts'][role] for role in ('unknown','merchant','provider','platform'))==4
    assert counts['names_missing']==2 and listing['role_counts']['unknown']==4


@pytest.mark.asyncio
async def test_unfinished_metadata_read_does_not_invent_an_archive_snapshot(db):
    seed_case(db)
    class Unavailable(MetadataSource):
        async def refresh_metadata(self):
            from wechat_agent.source.adapter import SourceError
            raise SourceError('source_unreachable')
    intent(db)
    result=await run_next(db,Services(source=Unavailable()))
    assert result.state=='failed'
    assert all(key not in result.counts for key in ('contacts_total','contacts_current','contacts_retained'))
