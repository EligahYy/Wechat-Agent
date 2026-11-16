import pytest
from tests.factories import seed_case
from wechat_agent.source.sync import SyncResult
from wechat_agent.source.coverage import assess_sync

def test_unknown_group_warning_does_not_block_but_known_failed_room_does(db):
    seed_case(db)
    from wechat_agent.contacts.conversations import resolve_contact_conversations
    from wechat_agent.source.contracts import ContactKey
    rooms=resolve_contact_conversations(db,ContactKey(account_id='acct-1',contact_id='merchant-a'))
    assert rooms
    result=SyncResult(successful_conversations=sorted(rooms),gaps=['source_group_membership_unverified'])
    assert assess_sync(db,'acct-1',{'merchant-a'},result).contacts['merchant-a'].can_analyze
    room=sorted(rooms)[0]
    result.successful_conversations.remove(room);result.failed_conversations=[room];result.gaps.append('source_timeout')
    assert not assess_sync(db,'acct-1',{'merchant-a'},result).contacts['merchant-a'].can_analyze

@pytest.mark.asyncio
async def test_v2_http_refresh_metadata_and_page_contract(db):
    import httpx
    from tests.test_source_adapter import NativeServer,adapter
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.operations.contracts import OperationScope
    class V2(NativeServer):
        def metadata(self):return {**super().metadata(),'patch_id':'wechat-agent.2'}
        def respond(self,request):
            result=super().respond(request)
            if request.url.path.endswith('/health'):
                value=result.json();value['cli_version']='0.7.4+wechat-agent.2'
                return httpx.Response(200,json=value)
            return result
    server=V2()
    server.groups=[{'username':'room@chatroom','members_state':'known','members':[{'user_name':'merchant-a','display_name':'商家'}]}]
    async with adapter(server) as source:
        result=await sync_scope(db,source,OperationScope(account_id='account-a'),None,conversation_ids=['room@chatroom'])
    assert not result.gaps
    paths=[r.url.path for r in server.requests]
    assert '/api/v1/identity/refresh' in paths
    assert result.inserted==3


def test_unresolved_archived_sender_issue_still_blocks_contact(db):
    seed_case(db)
    from wechat_agent.contacts.conversations import resolve_contact_conversations
    from wechat_agent.source.contracts import ContactKey
    rooms=resolve_contact_conversations(db,ContactKey(account_id='acct-1',contact_id='merchant-a'))
    db.execute("INSERT INTO source_issues(account_id,issue_id,conversation_id,message_id,source_revision,code,raw_json) VALUES('acct-1','old-conflict','group-1','old-message','r','message_sender_conflict','{}')")
    result=SyncResult(successful_conversations=sorted(rooms))
    assert not assess_sync(db,'acct-1',{'merchant-a'},result).contacts['merchant-a'].can_analyze


def test_contact_list_gaps_include_historical_author_without_membership(db):
    from wechat_agent.contacts.service import _source_gaps
    seed_case(db)
    db.execute("DELETE FROM members WHERE account_id='acct-1' AND conversation_id='group-1' AND contact_id='merchant-a'")
    db.execute("INSERT INTO source_issues(account_id,issue_id,conversation_id,message_id,source_revision,code,raw_json) VALUES('acct-1','historical','group-1','m','r','message_sender_missing','{}')")
    assert 'message_sender_missing' in _source_gaps(db,'acct-1','merchant-a')
