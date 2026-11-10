"""Legacy group exclusions must keep their scope, not turn into excluded people."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_workspace_queue import model
from test_workspace_queue import ready as ready

from wechat_agent.archive import register
from wechat_agent.crm import index_contacts, stable_actor
from wechat_agent.db import DB, now
from wechat_agent.identity import set_excluded
from wechat_agent.ingestion import ingest
from wechat_agent.services import allow_conversation
from wechat_agent.web import create_app
from wechat_agent.workspace.store import eligible, source_chats
from wechat_agent.workspace.views import source_people
from wechat_agent.workspace.whitelist import change, listing


def legacy(db, source_id, name):
    with db.tx() as c:
        c.execute(
            "INSERT INTO actor_exclusions VALUES('account',?,'旧版排除')", (source_id,)
        )
        c.execute(
            "INSERT INTO identity_metadata VALUES('account',?,?,?,'',?)",
            (source_id, name, name, now()),
        )
        c.execute(
            "INSERT INTO crm_contacts(id,account_id,source_id,name) VALUES(?,'account',?,?)",
            (stable_actor("account", source_id), source_id, name),
        )


def test_startup_moves_groups_to_conversations_with_backup_and_member_exclusion(
    db, record
):
    db.settings.bind_source("account")
    cid = allow_conversation(
        db, "fixture", "account", "123@chatroom", "服务商对接群", "group", egress=True
    )
    private = allow_conversation(
        db, "fixture", "account", "merchant", "真实商家", "private", egress=True
    )
    ingest(db, [record | {"conversation_id": "123@chatroom", "sender_id": "merchant"}])
    legacy(db, "123@chatroom", "服务商对接群")
    legacy(db, "colleague", "Claire")
    with db.tx() as c:
        c.execute("DROP VIEW effective_actor_exclusions")
        c.execute("PRAGMA user_version=15")
    migrated = DB(db.settings)
    assert migrated.rows(
        "SELECT followup_source,egress,allowlisted FROM conversations WHERE id=?",
        (cid,),
    )[0] == {"followup_source": 0, "egress": 1, "allowlisted": 1}
    assert listing(migrated)["total"] == 2
    assert {r["source_id"] for r in listing(migrated)["items"]} == {
        "colleague",
        "merchant",
    }
    group = listing(migrated, "conversations")["items"][0]
    assert (
        group["id"] == cid
        and group["kind"] == "group"
        and group["name"] == "服务商对接群"
    )
    assert not source_chats(migrated)
    assert len(migrated.rows("SELECT * FROM messages")) == 1
    assert not migrated.rows(
        "SELECT 1 FROM actor_exclusions WHERE source_id='merchant'"
    )
    assert not migrated.rows("SELECT * FROM usage")
    backups = list(db.settings.data_dir.glob("pre-v16-*.sqlite3"))
    assert len(backups) == 1 and backups[0].stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(backups[0]) as c:
        assert (
            c.execute(
                "SELECT reason FROM actor_exclusions WHERE source_id='123@chatroom'"
            ).fetchone()[0]
            == "旧版排除"
        )
    DB(db.settings)
    assert len(list(db.settings.data_dir.glob("pre-v16-*.sqlite3"))) == 1
    assert (
        len(db.rows("SELECT * FROM events WHERE kind='group_exclusion_repaired'")) == 1
    )
    change(migrated, "conversations", cid, False)
    assert {v["id"] for v in source_chats(migrated)} == {private, cid}
    assert listing(migrated)["total"] == 1  # Real colleague exclusion survives.


def test_classification_uses_stable_kind_and_id_never_name_and_is_account_scoped(db):
    db.settings.bind_source("account")
    cid = allow_conversation(
        db, "fixture", "account", "room-without-suffix", "A2-00268某物流", "group"
    )
    foreign = allow_conversation(
        db, "fixture", "other-account", "room-without-suffix", "其他账号同名", "group"
    )
    legacy(db, "room-without-suffix", "A2-00268某物流")
    legacy(db, "wxid-real-person", "A2-00268某物流")
    migrated = DB(db.settings)
    assert listing(migrated)["items"][0]["source_id"] == "wxid-real-person"
    assert listing(migrated, "conversations")["items"][0]["id"] == cid
    assert (
        db.rows("SELECT followup_source FROM conversations WHERE id=?", (foreign,))[0][
            "followup_source"
        ]
        == 1
    )
    with pytest.raises(ValueError, match="invalid_identity"):
        eligible(db, "room-without-suffix")


def test_unsynced_group_stays_excluded_and_is_moved_when_discovered(db):
    db.settings.bind_source("account")
    legacy(db, "pending@chatroom", "尚未同步的服务商群")
    DB(db.settings)
    assert listing(db)["total"] == 0
    pending = listing(db, "conversations")["items"][0]
    assert pending["kind"] == "group" and pending["pending"]
    assert pending["name"] == "尚未同步的服务商群"
    assert listing(db, "conversations", q="服务商")["total"] == 1
    register(
        db,
        [
            {
                "source_id": "pending@chatroom",
                "title": "服务商群",
                "kind": "group",
                "excluded": False,
            }
        ],
        1793890000,
    )
    actual = listing(db, "conversations")["items"][0]
    assert actual["id"] != pending["id"] and not actual.get("pending")
    assert not db.rows("SELECT * FROM actor_exclusions")
    assert not source_chats(db)
    register(
        db,
        [
            {
                "source_id": "pending@chatroom",
                "title": "群改名",
                "kind": "group",
                "excluded": False,
            }
        ],
        1793890000,
    )
    assert not source_chats(db)  # Rediscovery must not erase the exclusion.


def test_unsynced_group_can_be_restored_before_discovery(db):
    db.settings.bind_source("account")
    legacy(db, "pending@chatroom", "待同步群")
    item = listing(db, "conversations")["items"][0]
    change(db, "conversations", item["id"], False)
    assert listing(db, "conversations")["total"] == 0
    allow_conversation(
        db, "fixture", "account", "pending@chatroom", "已同步群", "group"
    )
    assert len(source_chats(db)) == 1
    assert not db.rows("SELECT * FROM usage")


def test_new_and_legacy_people_write_paths_reject_group_identity(db, record):
    db.settings.bind_source("account")
    allow_conversation(db, "fixture", "account", "room", "群聊", "group")
    ingest(db, [record | {"conversation_id": "room", "sender_id": "room"}])
    with db.tx() as c:
        index_contacts(c, "account")
    assert not db.rows("SELECT * FROM crm_contacts WHERE source_id='room'")
    assert not source_people(db)
    legacy(db, "room", "群聊")
    for excluded in (True, False):
        with pytest.raises(ValueError, match="群聊会话"):
            change(db, "people", "room", excluded)
        with pytest.raises(ValueError, match="群聊会话"):
            set_excluded(db, stable_actor("account", "room"), excluded, "同事")
    assert db.rows("SELECT * FROM actor_exclusions WHERE source_id='room'")
    # The compatibility list must not reintroduce the old group contacts.
    app = create_app(db.settings)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + db.token}
    assert (
        client.get("/api/crm/people?scope=archive", headers=headers).json()["total"]
        == 0
    )
    assert client.get("/api/crm/people", headers=headers).json()["total"] == 0


def test_conversation_whitelist_paginates_known_and_unsynced_groups_together(db):
    db.settings.bind_source("account")
    for n in range(51):
        allow_conversation(
            db,
            "fixture",
            "account",
            f"{n}@chatroom",
            f"群聊{n:02}",
            "group",
            followup_source=False,
        )
    legacy(db, "pending-a@chatroom", "群聊51")
    legacy(db, "pending-b@chatroom", "群聊52")
    first = listing(db, "conversations")
    last = listing(db, "conversations", page=99)
    assert first["total"] == 53 and len(first["items"]) == 50
    assert last["page"] == 2 and len(last["items"]) == 3
    assert all(r["kind"] == "group" for r in first["items"] + last["items"])
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in last["items"]}
    assert listing(db, "conversations", q="pending-b")["total"] == 1
    assert listing(db)["total"] == 0


def test_group_members_are_global_with_provenance_new_members_and_safe_restoration(
    db, record
):
    db.settings.bind_source("account")
    first = allow_conversation(
        db, "fixture", "account", "one@chatroom", "内部群一", "group"
    )
    second = allow_conversation(
        db, "fixture", "account", "two@chatroom", "内部群二", "group"
    )
    peer = allow_conversation(db, "fixture", "account", "staff", "私信同事", "private")
    for group in ("one@chatroom", "two@chatroom"):
        ingest(db, [record | {"conversation_id": group, "sender_id": "staff"}])
    with db.tx() as c:
        c.execute(
            "INSERT INTO contact_roles VALUES(?,'silent-staff','provider','静默成员')",
            (first,),
        )
    change(db, "people", "staff", True)
    change(db, "groups", first, True)
    change(db, "groups", second, True)
    people = listing(db)["items"]
    person = next(p for p in people if p["source_id"] == "staff")
    assert len(person["groups"]) == 2 and person["manual"]
    assert not person["can_restore"]
    assert any(
        p["source_id"] == "silent-staff" and p["name"] == "静默成员" for p in people
    )
    assert peer not in {c["id"] for c in source_chats(db)}
    with pytest.raises(ValueError, match="随白名单群"):
        change(db, "people", "staff", False)
    with pytest.raises(ValueError, match="excluded_person"):
        eligible(db, "silent-staff")
    ingest(
        db,
        [
            record
            | {
                "conversation_id": "one@chatroom",
                "source_id": "later",
                "sender_id": "new-staff",
            }
        ],
    )
    assert any(p["source_id"] == "new-staff" for p in listing(db)["items"])
    assert not any(p["source_id"] == "account" for p in listing(db)["items"])
    change(db, "groups", first, False)
    assert not any(p["source_id"] == "new-staff" for p in listing(db)["items"])
    assert (
        len(
            next(p for p in listing(db)["items"] if p["source_id"] == "staff")["groups"]
        )
        == 1
    )
    change(db, "groups", second, False)
    remaining = listing(db)["items"]
    assert (
        len(remaining) == 1
        and remaining[0]["source_id"] == "staff"
        and remaining[0]["manual"]
    )
    assert remaining[0]["can_restore"]
    change(db, "people", "staff", False)
    assert listing(db)["total"] == 0
    assert peer in {c["id"] for c in source_chats(db)}
    assert not db.rows("SELECT * FROM usage")


def test_legacy_private_exclusions_become_people_not_group_sessions(db):
    db.settings.bind_source("account")
    cid = allow_conversation(
        db,
        "fixture",
        "account",
        "colleague",
        "同事私信",
        "private",
        followup_source=False,
    )
    normalized = DB(db.settings)
    person = listing(normalized)["items"][0]
    assert person["source_id"] == "colleague" and person["manual"]
    assert listing(normalized, "groups")["total"] == 0
    assert (
        normalized.rows("SELECT followup_source FROM conversations WHERE id=?", (cid,))[
            0
        ]["followup_source"]
        == 1
    )
    assert not source_chats(normalized)
    change(normalized, "people", "colleague", False)
    assert {v["id"] for v in source_chats(normalized)} == {cid}
    with pytest.raises(ValueError, match="私信按人物管理"):
        change(normalized, "groups", cid, True)


def test_group_exclusion_during_analysis_revokes_member_result_from_normal_source(
    ready, record
):
    from wechat_agent.workspace import queue
    from wechat_agent.workspace.store import read

    group = allow_conversation(
        ready, "fixture", "account", "internal@chatroom", "内部群", "group", egress=True
    )
    ingest(
        ready,
        [
            record
            | {
                "conversation_id": "internal@chatroom",
                "source_id": "staff-membership",
                "sender_id": "merchant",
            }
        ],
    )
    excluded = []

    def pause(payload):
        if payload.get("phase") == "extract" and not excluded:
            excluded.append(True)
            change(ready, "groups", group, True)

    with model(ready, pause) as client:
        with pytest.raises(ValueError, match="workspace_stale_input"):
            queue.command(ready, "merchant", "start", background=False, client=client)
    with pytest.raises(ValueError, match="excluded_person"):
        read(ready, "merchant")
    assert not ready.rows("SELECT * FROM workspace_documents")
    assert ready.rows("SELECT * FROM usage")  # Already-sent usage is retained.
    assert not source_people(ready)
