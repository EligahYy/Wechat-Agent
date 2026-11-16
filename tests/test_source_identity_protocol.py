"""Consume only the pinned source capabilities and explicit attribution states."""
import pytest
from tests.test_source_adapter import NativeServer, adapter
from tests.test_source_probe import message
from wechat_agent.source.adapter import SourceError


@pytest.mark.asyncio
async def test_patched_metadata_preserves_field_states_and_scoped_member_names():
    server = NativeServer()
    server.people[0]['remark'] = {'value':None,'state':'unreadable'}
    server.groups = [{'username':'room@chatroom','members_state':'known','members':[
        {'user_name':'group-only','display_name':'群内甲'}]}]
    server.sessions[0].update(last_msg_sender='merchant-a', last_sender_display_name='会话原始名称')
    async with adapter(server) as source:
        report = await source.check()
        assert report.status == 'passed'
        assert report.facts['metadata']['mode'] == 'sqlcipher'
        people = await source.contacts()
        rooms = await source.conversations()
    assert next(p for p in people if p.key.contact_id == 'merchant-a').remark_state == 'unreadable'
    room = next(r for r in rooms if r.kind == 'group')
    assert room.member_ids == ['group-only']
    assert room.name_evidence[0].origin == 'group_member'
    assert room.name_evidence[0].value == '群内甲'
    private = next(r for r in rooms if r.conversation_id == 'merchant-a')
    assert private.name_evidence[0].value == '会话原始名称'
    assert all(not r.url.path.endswith('messages') for r in server.requests)


@pytest.mark.asyncio
async def test_legacy_source_is_available_for_diagnostics_but_cannot_archive_group_messages():
    server = NativeServer(); server.patched = False
    async with adapter(server) as source:
        assert (await source.check()).status == 'passed'
        assert await source.contacts()
        with pytest.raises(SourceError, match='source_patch_required'):
            await source.messages('room@chatroom',None,2)
    assert all(not r.url.path.endswith('messages') for r in server.requests)


@pytest.mark.asyncio
async def test_conflicting_sender_issue_keeps_both_attribution_candidates():
    server = NativeServer()
    server.rows = [{**message(talker='room@chatroom',sender=''),
        'sender_issue':'sender_prefix_conflict','sender_fallback':'fallback-person', 'sender_candidate':'candidate-person'}]
    async with adapter(server) as source:
        page = await source.messages('room@chatroom',None,2)
    assert not page.records and not page.complete
    assert page.issues[0].code == 'message_sender_conflict'
    assert page.issues[0].raw['sender_fallback'] == 'fallback-person'
    assert page.issues[0].raw['sender_candidate'] == 'candidate-person'


@pytest.mark.asyncio
async def test_changed_metadata_generation_cannot_be_mixed_across_pages():
    class Changing(NativeServer):
        def respond(self, request):
            result = super().respond(request)
            if request.url.path.endswith('/identity/contacts'): self.generation += 1
            return result
    server = Changing()
    async with adapter(server) as source:
        with pytest.raises(SourceError, match='source_metadata_changed'):
            await source.contacts()


@pytest.mark.asyncio
async def test_refresh_is_explicit_and_waits_for_a_new_successful_generation():
    server = NativeServer()
    async with adapter(server) as source:
        await source.check()
        await source.refresh_metadata()
        report = await source.check()
    assert report.facts['metadata']['generation'] == 1
    assert len([r for r in server.requests if r.method == 'POST']) == 1
    assert all(not r.url.path.endswith('messages') for r in server.requests)


@pytest.mark.asyncio
async def test_page_generation_must_match_the_health_generation():
    import httpx
    class StalePage(NativeServer):
        def respond(self, request):
            result = super().respond(request)
            if request.url.path.endswith('/identity/contacts'):
                value = result.json(); value['metadata']['generation'] = 99
                result = httpx.Response(200,json=value)
            return result
    async with adapter(StalePage()) as source:
        with pytest.raises(SourceError, match='source_metadata_changed'):
            await source.contacts()


@pytest.mark.asyncio
async def test_ready_health_cannot_claim_a_stale_name_resolver():
    server = NativeServer()
    server.metadata_override = {**server.metadata(),'generation':2,'resolver_generation':1}
    async with adapter(server) as source:
        assert (await source.check()).gaps == ['source_contract_invalid']


@pytest.mark.asyncio
async def test_conflict_marker_is_not_ignored_even_if_sender_was_not_cleared():
    server = NativeServer()
    server.rows = [{**message(talker='room@chatroom',sender='merchant-a'),
        'sender_issue':'sender_prefix_conflict','sender_fallback':'merchant-a','sender_candidate':'merchant-b'}]
    async with adapter(server) as source:
        page = await source.messages('room@chatroom',None,2)
    assert not page.records
    assert page.issues[0].code == 'message_sender_conflict'


@pytest.mark.asyncio
async def test_legacy_full_sync_stops_before_metadata_or_message_archive(db):
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.operations.contracts import OperationScope
    server = NativeServer(); server.patched = False
    before = db.total_changes
    async with adapter(server) as source:
        result = await sync_scope(db, source, OperationScope(account_id='account-a'), None)
    assert result.gaps == ['source_patch_required']
    assert db.total_changes == before
    assert all(r.url.path.endswith('health') for r in server.requests)


@pytest.mark.asyncio
async def test_synthetic_private_scope_is_distinct_from_a_recent_session():
    server = NativeServer()
    server.people.append({'user_name':'no-session-person','remark':'来源名称','nick_name':''})
    async with adapter(server) as source:
        rooms = await source.conversations()
    assert next(r for r in rooms if r.conversation_id == 'no-session-person').origin == 'metadata_candidate'
    assert next(r for r in rooms if r.conversation_id == 'merchant-a').origin == 'session'

@pytest.mark.asyncio
async def test_metadata_epoch_change_after_initial_health_stops_before_archive(db):
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.operations.contracts import OperationScope
    class ChangedAfterCheck(NativeServer):
        def respond(self, request):
            response = super().respond(request)
            if request.url.path.endswith('/health') and sum(r.url.path.endswith('/health') for r in self.requests) == 3:
                self.generation += 1
            return response
    before = db.total_changes
    async with adapter(ChangedAfterCheck()) as source:
        result = await sync_scope(db, source, OperationScope(account_id='account-a'), None, metadata_only=True)
    assert result.gaps == ['source_metadata_changed']
    assert db.total_changes == before


@pytest.mark.asyncio
async def test_metadata_epoch_is_kept_through_message_phase():
    server = NativeServer()
    async with adapter(server) as source:
        await source.check()
        await source.contacts()
        await source.conversations()
        server.generation += 1
        with pytest.raises(SourceError, match='source_metadata_changed'):
            await source.messages('room@chatroom',None,2)
    assert all(not request.url.path.endswith('/messages') for request in server.requests)


@pytest.mark.asyncio
async def test_direct_message_read_rejects_mid_page_metadata_refresh():
    class ChangedDuringMessages(NativeServer):
        def respond(self, request):
            response = super().respond(request)
            if request.url.path.endswith('/messages'):
                self.generation += 1
            return response
    async with adapter(ChangedDuringMessages()) as source:
        with pytest.raises(SourceError, match='source_metadata_changed'):
            await source.messages('room@chatroom',None,2)

@pytest.mark.asyncio
async def test_failed_group_name_read_keeps_last_title_but_explicit_empty_clears(db):
    from wechat_agent.source.sync import sync_scope
    from wechat_agent.operations.contracts import OperationScope
    server = NativeServer(); server.sessions = []
    server.people[-1].update(remark='业务群',nick_name='')
    async def refresh():
        async with adapter(server) as source:
            return await sync_scope(db,source,OperationScope(account_id='account-a'),None,metadata_only=True)
    assert not (await refresh()).gaps
    server.people[-1].update(remark={'value':None,'state':'unreadable'},nickname={'value':None,'state':'unreadable'})
    result = await refresh()
    assert 'source_name_read_failed' in result.gaps
    row = db.execute("SELECT title,title_state FROM conversations WHERE conversation_id='room@chatroom'").fetchone()
    assert tuple(row) == ('业务群','unreadable')
    server.people[-1].update(remark={'value':None,'state':'empty'},nickname={'value':None,'state':'empty'})
    assert not (await refresh()).gaps
    assert db.execute("SELECT title FROM conversations WHERE conversation_id='room@chatroom'").fetchone()[0] is None


@pytest.mark.asyncio
async def test_v2_stale_metadata_can_refresh_but_cannot_be_read_as_current():
    import httpx
    class V2(NativeServer):
        def metadata(self):
            return {**super().metadata(), 'patch_id':'wechat-agent.2'}
        def respond(self, request):
            if request.url.path.endswith('/identity/refresh'):
                self.refresh_state = 'ready'
            response = super().respond(request)
            if request.url.path.endswith('/health'):
                data = response.json()
                data['cli_version'] = '0.7.4+wechat-agent.2'
                data['ready'] = self.refresh_state == 'ready'
                return httpx.Response(200, json=data)
            return response
    server = V2(); server.refresh_state = 'stale'
    async with adapter(server) as source:
        assert (await source.check()).gaps == ['source_metadata_changed']
        await source.refresh_metadata()
        assert (await source.check()).status == 'passed'
