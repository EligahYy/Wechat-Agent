"""Replay the verified wx-cli wire protocol without opening a real WeChat account."""

import json

import httpx
import pytest

from tests.test_source_probe import envelope, health, message


class NativeServer:
    def __init__(self):
        self.requests = []
        self.account = "account-a"
        self.people = [{"user_name": "merchant-a", "remark": "Same", "nick_name": "Merchant"},
                       {"user_name": "merchant-b", "remark": "Same", "nick_name": "Merchant"},
                       {"user_name": "room@chatroom", "remark": "", "nick_name": "Real room"}]
        self.sessions = [{"username": "merchant-a", "display_name": "Same"},
                         {"username": "room@chatroom", "display_name": "Real room"}]
        self.rows = [message(i, talker="room@chatroom") for i in range(1, 4)]
        self.skipped = 0
        self.patched = True
        self.groups = []
        self.generation = 0
        self.refresh_state = 'ready'
        self.metadata_override = None

    def respond(self, request):
        self.requests.append(request)
        if request.url.path.endswith("health"):
            value = health(account=self.account)
            if self.patched:
                value.update(cli_version='0.7.4+wechat-agent.1', metadata=self.metadata())
            return httpx.Response(200, json=value)
        if request.url.path.endswith('/identity/refresh'):
            self.generation += 1
            return httpx.Response(202, json={'generation': self.generation - 1, 'refresh_state':'queued'})
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        if request.url.path.endswith('/identity/contacts'):
            def field(row, key):
                value = row.get(key)
                if isinstance(value, dict): return value
                return {'value': value or None, 'state': 'known' if value else 'empty'}
            rows = [{'user_name': row['user_name'], 'remark':field(row,'remark'),
                     'nickname':field(row,'nick_name'), 'relationship':'unknown'} for row in self.people]
        elif request.url.path.endswith('/identity/groups'):
            rows = self.groups
        elif request.url.path.endswith("contacts"):
            rows = self.people
        elif request.url.path.endswith("sessions"):
            rows = self.sessions
        else:
            rows = self.rows
        value = envelope(rows[offset:offset + limit], offset=offset, limit=limit,
                         total=len(rows), skipped=self.skipped)
        if '/identity/' in request.url.path: value['metadata'] = self.metadata()
        return httpx.Response(200, json=value)

    def metadata(self):
        return self.metadata_override or {'contract':'wechat-agent-source-v1', 'patch_id':'wechat-agent.1',
            'mode':'sqlcipher','generation':self.generation,'resolver_generation':self.generation,
            'refreshed_at':'2026-11-12T00:00:00Z','refresh_state':self.refresh_state}


def adapter(server):
    from wechat_agent.source.adapter import WXCLIAdapter
    from wechat_agent.source.probe import SourceConfig
    return WXCLIAdapter(SourceConfig(expected_account_id="account-a"), transport=httpx.MockTransport(server.respond))


@pytest.mark.asyncio
async def test_live_adapter_preserves_stable_people_and_real_group_titles():
    server = NativeServer()
    server.people += [{"user_name": f"person-{i}", "remark": "", "nick_name": f"Person {i}"} for i in range(202)]
    async with adapter(server) as source:
        people = await source.contacts()
        rooms = await source.conversations()
    assert len(people) == 205  # 204 people plus the bound self account; group is separate.
    assert all(not person.key.contact_id.endswith("@chatroom") for person in people)
    assert {person.key.contact_id for person in people if person.is_self} == {"account-a"}
    assert len([person for person in people if person.remark == "Same"]) == 2
    room = next(row for row in rooms if row.conversation_id == "room@chatroom")
    assert room.title == "Real room"
    assert room.member_ids == []
    assert len([r for r in server.requests if r.url.path.endswith("contacts")]) == 2
    assert all(r.method == "GET" for r in server.requests)
    assert all(r.url.params["show_hidden"] == "1" for r in server.requests if not r.url.path.endswith("health"))


@pytest.mark.asyncio
async def test_native_message_cursor_keeps_scope_cutoff_and_source_window():
    server = NativeServer()
    async with adapter(server) as source:
        first = await source.messages("room@chatroom", None, 2)
        second = await source.messages("room@chatroom", first.next_cursor, 2)
    assert len(first.records) == 2
    assert not first.complete
    assert second.complete
    assert second.next_cursor is None
    assert second.records[0].message_id == "wx-cli:room%40chatroom:3"
    requests = [r for r in server.requests if r.url.path.endswith("messages")]
    assert [r.url.params["offset"] for r in requests] == ["0", "2"]
    assert requests[0].url.params["until"] == requests[1].url.params["until"]
    assert all(r.url.params["order"] == "asc" for r in requests)


@pytest.mark.asyncio
async def test_account_change_cannot_read_message_data():
    from wechat_agent.source.adapter import SourceError
    server = NativeServer()
    server.account = "another-account"
    async with adapter(server) as source:
        with pytest.raises(SourceError, match="source_account_mismatch"):
            await source.messages("room@chatroom", None, 2)
    assert [r.url.path for r in server.requests] == ["/api/v1/health"]


@pytest.mark.asyncio
async def test_bad_sender_keeps_raw_issue_and_blocks_cursor(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    server.rows[0].update(sender="", content={"Text": "private-unattributed-text"})
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert len(page.records) == 1
    assert page.gaps == ["message_sender_missing"]
    assert not page.complete
    archive_page(db, page)
    row = db.execute("SELECT code,raw_json FROM source_issues").fetchone()
    assert row["code"] == "message_sender_missing"
    assert "private-unattributed-text" in row["raw_json"]
    assert db.execute("SELECT cursor FROM sync_cursors").fetchone()[0] is None
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_system_event_is_archived_without_person(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    server.rows[0].update(sender="", content={"System": "Synthetic system event"}, msg_type=10000)
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert page.gaps == []
    archive_page(db, page)
    assert db.execute("SELECT sender_id FROM messages WHERE kind='system'").fetchone()[0] is None
    assert db.execute("SELECT COUNT(*) FROM source_issues").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_corrected_sender_resolves_issue_and_keeps_original_raw_evidence(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    server.rows[0]["sender"] = ""
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
        archive_page(db, page)
        archive_page(db, page)
        server.rows[0]["sender"] = "merchant-a"
        fixed = await source.messages("room@chatroom", None, 2)
        archive_page(db, fixed)
    issues = db.execute("SELECT raw_json,resolved FROM source_issues").fetchall()
    assert len(issues) == 1
    assert json.loads(issues[0]["raw_json"])["sender"] == ""
    assert issues[0]["resolved"] == 1
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


@pytest.mark.asyncio
async def test_cursor_cannot_be_reused_for_another_conversation():
    from wechat_agent.source.adapter import SourceError
    server = NativeServer()
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
        before = len(server.requests)
        with pytest.raises(SourceError, match="source_cursor_scope_mismatch"):
            await source.messages("merchant-a", page.next_cursor, 2)
        assert len(server.requests) == before


@pytest.mark.asyncio
async def test_shard_skips_cannot_become_complete_or_advance_cursor():
    server = NativeServer()
    server.skipped = 1
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert "source_rows_skipped" in page.gaps
    assert page.next_cursor is None
    assert not page.complete


@pytest.mark.asyncio
async def test_source_response_for_different_conversation_is_refused():
    from wechat_agent.source.adapter import SourceError
    server = NativeServer()
    server.rows[0]["talker"] = "another-room@chatroom"
    async with adapter(server) as source:
        with pytest.raises(SourceError, match="source_message_scope_mismatch"):
            await source.messages("room@chatroom", None, 2)


@pytest.mark.asyncio
async def test_page_order_regression_is_reported_without_advancing():
    from wechat_agent.source.adapter import SourceError
    server = NativeServer()
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
        server.rows[2] = message(1, talker="room@chatroom")
        with pytest.raises(SourceError, match="source_page_no_progress"):
            await source.messages("room@chatroom", page.next_cursor, 2)


@pytest.mark.asyncio
async def test_server_failure_does_not_echo_its_private_body():
    from wechat_agent.source.adapter import WXCLIAdapter, SourceError
    from wechat_agent.source.probe import SourceConfig
    async with WXCLIAdapter(SourceConfig(expected_account_id="account-a"),
                            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="private-server-body"))) as source:
        with pytest.raises(SourceError) as caught:
            await source.contacts()
    assert str(caught.value) == "source_server_error"


@pytest.mark.asyncio
async def test_group_id_as_system_actor_is_not_created_as_a_person(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    server.rows[0].update(sender="room@chatroom", msg_type=10000, content={"System": "Synthetic event"})
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert page.records[0].sender_id is None
    assert page.records[0].raw["sender"] == "room@chatroom"
    archive_page(db, page)
    assert db.execute("SELECT COUNT(*) FROM contacts WHERE contact_id='room@chatroom'").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_normal_chat_with_group_sender_is_kept_as_an_issue(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    server.rows[0]["sender"] = "room@chatroom"
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert page.gaps == ["message_sender_missing"]
    archive_page(db, page)
    assert db.execute("SELECT COUNT(*) FROM source_issues").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_unidentified_rows_keep_separate_observations_instead_of_body_hash_ids(db):
    from wechat_agent.source.repository import archive_page
    server = NativeServer()
    unidentified = message(0, talker="room@chatroom")
    server.rows = [dict(unidentified), dict(unidentified)]
    async with adapter(server) as source:
        page = await source.messages("room@chatroom", None, 2)
    assert page.gaps == ["source_message_id_unavailable"]
    assert len(page.issues) == 2
    assert all(issue.message_id is None for issue in page.issues)
    archive_page(db, page)
    assert db.execute("SELECT COUNT(*) FROM source_issues").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
