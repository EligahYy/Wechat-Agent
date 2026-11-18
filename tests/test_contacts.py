"""Unified identities, literal search and versioned manual role changes."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from datetime import datetime
import threading

import pytest


@contextmanager
def archive(client):
    from wechat_agent.storage.db import open_db
    with closing(open_db(client.app.state.database_path)) as conn:
        yield conn


@pytest.fixture
def contacts_client(client):
    from tests.factories import seed_case
    from tests.fakes.source import FakeSource
    with archive(client) as conn:
        seed_case(conn)
    client.app.state.services.source = FakeSource()
    return client


def fetch(client, **params):
    return client.get("/api/contacts", params={"account_id": "acct-1", **params})


def change(client, ids, role="provider", versions=None):
    return client.patch("/api/contacts/roles", json={
        "account_id": "acct-1", "role": role,
        "items": [{"key": {"account_id": "acct-1", "contact_id": cid},
                   "expected_version": (versions or {}).get(cid, 1)} for cid in ids]})


def test_contact_limit_is_twenty(client):
    assert client.get("/api/contacts", params={"account_id": "acct-1", "page_size": 21}).status_code == 422


def test_contacts_are_twenty_eight_people_in_twenty_and_eight_pages(contacts_client):
    first = fetch(contacts_client).json()
    second = fetch(contacts_client, page=2).json()
    assert first["total"] == second["total"] == 28
    assert [len(first["items"]), len(second["items"])] == [20, 8]
    ids = [row["key"]["contact_id"] for row in first["items"] + second["items"]]
    assert len(set(ids)) == 28
    assert not {"self-1", "group-1", "dm-a"} & set(ids)
    assert first["role_counts"] == {"all": 28, "merchant": 6, "provider": 8, "platform": 7, "unknown": 7}


def test_one_person_has_private_and_group_sources_without_duplicate_rows(contacts_client):
    result = fetch(contacts_client, q="甲").json()
    assert result["total"] == 1
    item = result["items"][0]
    assert item["key"] == {"account_id": "acct-1", "contact_id": "merchant-a"}
    assert {source["conversation_id"] for source in item["sources"]} == {"dm-a", "group-1"}
    assert item["copy_name"] == "商家甲"
    assert item["profile_status"] == "pending"
    assert item["profile_updated_at"] is None


def test_source_group_titles_are_outside_contact_name_search(contacts_client):
    result = fetch(contacts_client, q="业务群").json()
    assert result["total"] == 0
    assert result["items"] == []


def test_duplicate_display_names_are_distinct_stable_people(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET remark='商家甲' WHERE contact_id='merchant-b'")
    result = fetch(contacts_client, q="商家甲").json()
    assert result["total"] == 2
    assert {row["key"]["contact_id"] for row in result["items"]} == {"merchant-a", "merchant-b"}


@pytest.mark.parametrize("query,name", [("%", "100%货主"), ("_", "literal_name"), ("*", "星*号"), ("\\", "路径\\客服")])
def test_search_wildcards_are_literal(contacts_client, query, name):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET remark=? WHERE contact_id='contact-01'", (name,))
    result = fetch(contacts_client, q=query).json()
    assert result["total"] == 1
    assert result["items"][0]["key"]["contact_id"] == "contact-01"


def test_role_filter_counts_and_out_of_range_pages_are_consistent(contacts_client):
    result = fetch(contacts_client, role="merchant").json()
    assert result["total"] == 6
    assert all(row["role"] == "merchant" for row in result["items"])
    assert result["role_counts"]["all"] == 28
    assert fetch(contacts_client, role="merchant", page=20).json()["items"] == []


def test_missing_name_never_copies_wxid(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET remark=NULL,nickname=NULL WHERE contact_id='contact-01'")
    item = next(item for page in (1,2) for item in fetch(contacts_client,page=page).json()["items"] if item["key"]["contact_id"]=="contact-01")
    assert item["display_name"] == "名称缺失"
    assert item["display_name_source"] == "missing"
    assert item["copy_name"] is None
    assert item["profile_status"] == "no_data"


def test_latest_message_sorts_by_time_value_not_offset_or_sync_time(contacts_client):
    from tests.factories import make_message, make_page
    from wechat_agent.source.repository import archive_page
    with archive(contacts_client) as conn:
        for cid, room, sent_at in [("contact-01", "dm-old", "2026-11-12T23:00:00+14:00"),
                                   ("contact-02", "dm-new", "2026-11-12T09:30:00+00:00")]:
            message = make_message(sender_id=cid, conversation_id=room, message_id=f"fixture:{room}:1",
                                   sent_at=datetime.fromisoformat(sent_at))
            archive_page(conn, make_page([message], conversation_id=room, conversation_kind="private"))
    items = fetch(contacts_client).json()["items"]
    assert items[0]["key"]["contact_id"] == "contact-02"
    assert items[1]["key"]["contact_id"] == "contact-01"
    assert items[1]["last_message_at"] == "2026-11-12T23:00:00+14:00"


def test_read_and_write_cannot_select_another_accounts_archive(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("INSERT INTO accounts(account_id) VALUES ('other-account')")
        conn.execute("INSERT INTO contacts(account_id,contact_id,remark) VALUES ('other-account','merchant-a','private-other')")
    response = fetch(contacts_client, account_id="other-account")
    assert response.status_code == 403
    assert "private-other" not in response.text
    response = contacts_client.patch("/api/contacts/roles", json={
        "account_id": "acct-1", "role": "provider", "items": [
            {"key": {"account_id": "acct-1", "contact_id": "merchant-a"}, "expected_version": 1},
            {"key": {"account_id": "other-account", "contact_id": "merchant-a"}, "expected_version": 1}]})
    assert response.status_code == 403
    assert fetch(contacts_client, q="甲").json()["items"][0]["role"] == "merchant"


def test_single_archived_account_works_offline_and_multiple_need_explicit_binding(contacts_client):
    contacts_client.app.state.services.source = None
    assert fetch(contacts_client).status_code == 200
    with archive(contacts_client) as conn, conn:
        conn.execute("INSERT INTO accounts(account_id) VALUES ('other-account')")
    response = fetch(contacts_client)
    assert response.status_code == 409
    assert response.json()["code"] == "account_binding_required"


def test_role_change_updates_only_selected_contact_and_preserves_originals(contacts_client):
    response = change(contacts_client, ["merchant-a"])
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "succeeded"
    assert result["updated"][0]["role_version"] == 2
    assert result["failed"] == []
    with archive(contacts_client) as conn:
        assert tuple(conn.execute("SELECT role,role_version FROM contacts WHERE contact_id='merchant-a'").fetchone()) == ("provider", 2)
        assert tuple(conn.execute("SELECT role,role_version FROM contacts WHERE contact_id='merchant-b'").fetchone()) == ("merchant", 1)
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM message_revisions").fetchone()[0] == 4


def test_stale_version_and_partial_batch_are_explicit(contacts_client):
    response = change(contacts_client, ["merchant-a", "merchant-b"], versions={"merchant-b": 99})
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "role_version_conflict"
    result = body["details"]
    assert result["status"] == "partial"
    assert result["updated"][0]["key"]["contact_id"] == "merchant-a"
    assert result["failed"][0]["key"]["contact_id"] == "merchant-b"
    assert result["failed"][0]["current_version"] == 1
    retry = change(contacts_client, ["merchant-a"], role="platform")
    assert retry.status_code == 409
    assert fetch(contacts_client, q="甲").json()["items"][0]["role"] == "provider"


def test_same_role_is_a_noop_and_self_is_locked(contacts_client):
    response = change(contacts_client, ["merchant-a"], role="merchant")
    assert response.json()["updated"][0]["changed"] is False
    assert response.json()["updated"][0]["role_version"] == 1
    response = change(contacts_client, ["self-1"], role="merchant")
    assert response.status_code == 409
    assert response.json()["details"]["failed"][0]["code"] == "self_role_locked"


def test_invalid_or_duplicate_batch_is_rejected_without_echoing_private_input(contacts_client):
    assert change(contacts_client, ["merchant-a", "merchant-a"]).status_code == 422
    response = change(contacts_client, ["merchant-a"], role="private-secret-value")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "private-secret-value" not in response.text
    assert fetch(contacts_client, q="甲").json()["items"][0]["role_version"] == 1


def test_nonmerchant_only_stops_queued_analysis_not_source_or_other_people(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("""INSERT INTO operations(account_id,id,action,idempotency_key,state,phase)
                      VALUES ('acct-1','batch','sync_and_organize','batch-key','queued','queued')""")
        for item_id, cid, state, phase in [("analysis-a", "merchant-a", "queued", "analysis"),
                                            ("running-a", "merchant-a", "running", "analysis"),
                                            ("source-a", "merchant-a", "queued", "source"),
                                            ("analysis-b", "merchant-b", "queued", "analysis")]:
            conn.execute("""INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,state,phase)
                          VALUES ('acct-1','batch',?,?,?,?)""", (item_id, cid, state, phase))
    assert change(contacts_client, ["merchant-a"]).status_code == 200
    with archive(contacts_client) as conn:
        rows = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT item_id,state,generation FROM operation_items")}
        assert rows == {"analysis-a": ("stopped", 2), "running-a": ("running", 1),
                        "source-a": ("queued", 1), "analysis-b": ("queued", 1)}
        assert conn.execute("SELECT state FROM operations WHERE id='batch'").fetchone()[0] == "queued"


def test_storage_error_rolls_back_entire_write_and_hides_exception(contacts_client):
    with archive(contacts_client) as conn:
        conn.executescript("""CREATE TRIGGER fail_role BEFORE UPDATE ON contacts WHEN new.contact_id='merchant-b'
                            BEGIN SELECT RAISE(ABORT,'private-failure-secret'); END;""")
    response = change(contacts_client, ["merchant-a", "merchant-b"])
    assert response.status_code == 503
    assert "private-failure-secret" not in response.text
    with archive(contacts_client) as conn:
        assert list(conn.execute("SELECT DISTINCT role_version FROM contacts WHERE contact_id IN ('merchant-a','merchant-b')"))[0][0] == 1
        assert conn.execute("SELECT COUNT(*) FROM contacts WHERE contact_id IN ('merchant-a','merchant-b') AND role='merchant'").fetchone()[0] == 2


def test_concurrent_manual_edits_have_one_winner(contacts_client):
    from wechat_agent.contacts.service import set_roles
    from wechat_agent.source.contracts import ContactKey
    from wechat_agent.storage.db import open_db
    barrier = threading.Barrier(2)
    def write(role):
        with closing(open_db(contacts_client.app.state.database_path)) as conn:
            barrier.wait(timeout=3)
            return set_roles(conn, [ContactKey(account_id="acct-1", contact_id="merchant-a")], role, {"merchant-a": 1})
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(write, "provider")
        two = pool.submit(write, "platform")
        results = [one.result(timeout=5), two.result(timeout=5)]
    assert sum(len(row.updated) for row in results) == 1
    assert sum(len(row.failed) for row in results) == 1
    with archive(contacts_client) as conn:
        assert conn.execute("SELECT role_version FROM contacts WHERE contact_id='merchant-a'").fetchone()[0] == 2


@pytest.mark.parametrize("write", [False, True])
def test_api_does_not_recreate_a_missing_archive(contacts_client, write):
    path = contacts_client.app.state.database_path
    path.unlink()
    response = change(contacts_client, ["merchant-a"]) if write else fetch(contacts_client)
    assert response.status_code == 503
    assert not path.exists()
    assert str(path) not in response.text


def test_configured_account_controls_multi_account_archive(contacts_client, tmp_path):
    from wechat_agent.config import Settings
    path = tmp_path / "source-config.json"
    path.write_text('{"expected_account_id":"acct-1"}')
    contacts_client.app.state.settings = Settings(data_dir=tmp_path, source_config=path)
    contacts_client.app.state.services.source = None
    with archive(contacts_client) as conn, conn:
        conn.execute("INSERT INTO accounts(account_id) VALUES ('other-account')")
    assert fetch(contacts_client).status_code == 200
    assert fetch(contacts_client, account_id="other-account").status_code == 403


@pytest.mark.parametrize("config", ['{"expected_account_id":"other-account"}', 'private-invalid-config'])
def test_conflicting_or_invalid_binding_does_not_expose_contacts(contacts_client, tmp_path, config):
    from wechat_agent.config import Settings
    path = tmp_path / "source-config.json"
    path.write_text(config)
    contacts_client.app.state.settings = Settings(data_dir=tmp_path, source_config=path)
    response = fetch(contacts_client)
    assert response.status_code == 503
    assert "商家甲" not in response.text
    assert "private-invalid-config" not in response.text


def test_source_gaps_stay_visible_until_the_latest_retry_succeeds(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE sync_cursors SET complete=0,gaps_json='[\"message_sender_missing\"]' WHERE conversation_id='dm-a'")
    item = fetch(contacts_client, q="甲").json()["items"][0]
    assert item["source_gaps"] == ["message_sender_missing", "source_history_incomplete"]
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE sync_cursors SET complete=1,gaps_json='[]' WHERE conversation_id='dm-a'")
    assert fetch(contacts_client, q="甲").json()["items"][0]["source_gaps"] == []


def test_targeted_queued_analysis_operation_stops_but_sync_remains_available(contacts_client):
    with archive(contacts_client) as conn, conn:
        for operation_id, phase in [("analysis-one", "analysis"), ("source-one", "source")]:
            conn.execute("""INSERT INTO operations(account_id,id,contact_id,action,idempotency_key,state,phase)
                          VALUES ('acct-1',?,'merchant-a','sync_and_organize',?,'queued',?)""",
                         (operation_id, operation_id, phase))
    response = change(contacts_client, ["merchant-a"])
    assert response.json()["updated"][0]["cancelled_operations"] == 1
    with archive(contacts_client) as conn:
        assert {row[0]: row[1] for row in conn.execute("SELECT id,state FROM operations")} == {
            "analysis-one": "stopped", "source-one": "queued"}


def test_name_falls_back_to_real_nickname_but_never_identifier(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET remark='',nickname='实际昵称' WHERE contact_id='contact-01'")
    item = fetch(contacts_client, q="实际昵称").json()["items"][0]
    assert item["display_name_source"] == "nickname"
    assert item["copy_name"] == "实际昵称"
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET nickname=contact_id WHERE contact_id='contact-01'")
    assert next(item for page in (1,2) for item in fetch(contacts_client,page=page).json()["items"] if item["key"]["contact_id"]=="contact-01")["copy_name"] is None


def test_list_counts_and_rows_share_one_read_snapshot_during_role_change(contacts_client, monkeypatch):
    from wechat_agent.api import contacts as route
    real_open = route.open_existing_db
    changed = False
    def open_with_concurrent_change(path, **kwargs):
        conn = real_open(path, **kwargs)
        def change_between_queries(statement):
            nonlocal changed
            if not changed and statement.startswith("SELECT c.role,COUNT"):
                changed = True
                with closing(real_open(path)) as writer, writer:
                    writer.execute("UPDATE contacts SET role='provider',role_version=2 WHERE contact_id='merchant-a'")
        conn.set_trace_callback(change_between_queries)
        return conn
    monkeypatch.setattr(route, "open_existing_db", open_with_concurrent_change)
    response = fetch(contacts_client, role="merchant")
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == result["role_counts"]["merchant"] == len(result["items"]) == 6
    assert fetch(contacts_client, role="merchant").json()["total"] == 5


def test_search_work_stays_bounded_for_thousands_of_contacts_and_shared_groups(db):
    from wechat_agent.contacts.service import list_contacts
    with db:
        db.execute("INSERT INTO accounts(account_id) VALUES('scale-account')")
        db.executemany("INSERT INTO contacts(account_id,contact_id,nickname) VALUES('scale-account',?,?)",
            [(f'person-{i}',f'货主{i}') for i in range(2420)])
        db.executemany("INSERT INTO conversations(account_id,conversation_id,kind,title) VALUES('scale-account',?,'group',?)",
            [(f'room-{g}',f'TEMU业务{g}' if g%2 else f'普通群{g}') for g in range(80)])
        db.executemany("INSERT INTO members(account_id,conversation_id,contact_id) VALUES('scale-account',?,?)",
            [(f'room-{g}',f'person-{i}') for i in range(2420) for g in range(80) if (i+g)%8==0])
    import sqlite3
    for query,expected in [('Temu',0),('货主2419',1),('货主',2420),('no-matching-name',0)]:
        previous_limit=db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER,512)
        steps=[0]
        def budget():
            steps[0]+=1000
            return steps[0]>8_000_000
        db.set_progress_handler(budget,1000)
        try:
            result=list_contacts(db,'scale-account',q=query)
        finally:
            db.set_progress_handler(None,0)
            db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER,previous_limit)
        assert result['total']==expected
        assert result['role_counts']['all']==expected
        assert len(result['items'])==min(20,expected)


def test_search_matches_nickname_or_remark_but_not_ids_or_source_titles(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE contacts SET remark='独立备注',nickname='Temu昵称' WHERE contact_id='merchant-a'")
    for query in ('独立备注','temu昵称'):
        result=fetch(contacts_client,q=query).json()
        assert result['total']==1
        assert result['items'][0]['key']['contact_id']=='merchant-a'
    for query in ('merchant-a','业务群'):
        result=fetch(contacts_client,q=query).json()
        assert result['total']==result['role_counts']['all']==0


def test_search_ignores_surrounding_whitespace(contacts_client):
    assert fetch(contacts_client,q='  商家甲  ').json()['total']==1


def test_name_search_does_not_rank_unrelated_message_history(db):
    from tests.factories import seed_case
    from wechat_agent.contacts.service import list_contacts
    seed_case(db)
    before=list_contacts(db,'acct-1',q='商家甲')
    with db:
        db.execute("INSERT INTO conversations(account_id,conversation_id,kind,title) VALUES('acct-1','unrelated-room','group','无关群')")
        db.executemany("""INSERT INTO messages(account_id,message_id,conversation_id,sender_id,sent_at,kind,body,source_revision,raw_json)
            VALUES('acct-1',?,'unrelated-room','contact-01','2026-11-11T00:00:00+00:00','text','synthetic','r1','{}')""",
            [(f'unrelated-{i}',) for i in range(20000)])
    steps=[0]
    def budget():
        steps[0]+=1000
        return steps[0]>500_000
    db.set_progress_handler(budget,1000)
    try:
        after=list_contacts(db,'acct-1',q='商家甲')
    finally:
        db.set_progress_handler(None,0)
    assert after['items']==before['items']
    assert after['total']==before['total']==1


def test_batch_organization_projects_each_customer_outcome(contacts_client):
    with archive(contacts_client) as conn, conn:
        conn.execute("""
            INSERT INTO operations(account_id,id,action,state,phase,idempotency_key,error_code)
            VALUES('acct-1','batch','sync_and_organize','failed','analysis','batch','analysis_budget_paused')
        """)
        conn.executemany("""
            INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,phase,state,role_version,error_code)
            VALUES('acct-1','batch',?,?,'analysis',?,1,?)
        """, [
            ('analysis:merchant-a', 'merchant-a', 'failed', 'empty_result'),
            ('analysis:merchant-b', 'merchant-b', 'queued', None),
        ])
    def entries():
        result = fetch(contacts_client, role='merchant').json()
        return {item['key']['contact_id']: item for item in result['items']}

    rows = entries()
    assert rows['merchant-a']['profile_status'] == 'pending'
    assert rows['merchant-a']['organization_attempt']['status'] == 'no_findings'
    assert rows['merchant-b']['organization_attempt']['status'] == 'paused'
    assert sum(row['organization_attempt'] is not None for row in rows.values()) == 2
    with archive(contacts_client) as conn, conn:
        conn.execute("UPDATE operations SET state='stopped',error_code='user_stopped' WHERE id='batch'")
    rows = entries()
    assert rows['merchant-a']['organization_attempt']['status'] == 'no_findings'
    assert rows['merchant-b']['organization_attempt']['status'] == 'stopped'


def test_profile_status_filters_before_pagination(contacts_client):
    expected = fetch(contacts_client, role='merchant').json()['items']
    without_data = [row['key'] for row in expected if row['profile_status'] == 'no_data']
    assert len(without_data) >= 2
    for index, key in enumerate(without_data, 1):
        result = fetch(contacts_client, role='merchant', profile_status='no_data', page_size=1, page=index).json()
        assert result['total'] == len(without_data)
        assert [row['key'] for row in result['items']] == [key]
    assert fetch(contacts_client, profile_status='invalid').status_code == 422
