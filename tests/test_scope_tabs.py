import httpx
from fastapi.testclient import TestClient

from wechat_agent.collector import Collector
from wechat_agent.db import uid
from wechat_agent.identity import sync_contacts
from wechat_agent.services import allow_conversation
from wechat_agent.source_scope import list_sources
from wechat_agent.web import create_app


def populate(db):
    db.settings.source_account = db.settings.self_id = "account"
    with db.tx() as c:
        for followup, n in ((1, 51), (0, 53)):
            for i in range(n):
                c.execute(
                    "INSERT INTO conversations(id,source,account_id,source_id,title,kind,allowlisted,egress,followup_source) VALUES(?,'wx_cli','account',?,?,'private',1,0,?)",
                    (uid(), f"p-{followup}-{i}", f"名称{followup}-{i:03}", followup),
                )
                sid = f"p-{followup}-{i}"
                c.execute(
                    "INSERT INTO crm_contacts(id,account_id,source_id,name) VALUES(?,'account',?,?)",
                    (sid, sid, sid),
                )
                if not followup:
                    c.execute(
                        "INSERT INTO actor_exclusions VALUES('account',?,'同事')",
                        (sid,),
                    )


def test_conversation_tabs_are_disjoint_and_page_at_fifty(db):
    populate(db)
    normal = list_sources(db, scope="customer")
    excluded = list_sources(db, scope="archive")
    assert len(normal["items"]) == len(excluded["items"]) == 50
    assert normal["total"] == 51 and excluded["total"] == 53
    assert normal["pages"] == excluded["pages"] == 2
    assert len(list_sources(db, scope="customer", page=2)["items"]) == 1
    assert len(list_sources(db, scope="archive", page=2)["items"]) == 3
    assert not (
        {r["id"] for r in normal["items"]} & {r["id"] for r in excluded["items"]}
    )


def test_people_tabs_are_paginated_and_account_scoped(db):
    populate(db)
    app = create_app(db.settings)
    with TestClient(app) as client:
        h = {"Authorization": "Bearer " + db.token}
        normal = client.get("/api/crm/people", headers=h).json()
        excluded = client.get("/api/crm/people?scope=archive&page=2", headers=h).json()
        assert len(normal["items"]) == 50 and normal["total"] == 51
        assert len(excluded["items"]) == 3 and excluded["total"] == 53
        assert all(r["excluded"] == 1 for r in excluded["items"])
        assert client.get("/api/crm/people?page=0", headers=h).status_code == 422


def source(db, handler):
    return Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(handler)
        ),
    )


def test_group_contact_sync_updates_title_without_analysis(db):
    db.settings.source_account = db.settings.self_id = "account"
    cid = allow_conversation(
        db, "wx_cli", "account", "123@chatroom", "123@chatroom", "group"
    )

    def handler(req):
        if req.url.path.endswith("health"):
            return httpx.Response(
                200, json={"ready": True, "current_account": {"wxid": "account"}}
            )
        return httpx.Response(
            200,
            json={
                "items": [{"user_name": "123@chatroom", "nick_name": "德国备货三方群"}],
                "paging": {"has_more": False},
            },
        )

    sync_contacts(db, source(db, handler))
    assert (
        db.rows("SELECT title FROM conversations WHERE id=?", (cid,))[0]["title"]
        == "德国备货三方群"
    )
    assert not db.rows("SELECT * FROM usage")
    assert not db.rows("SELECT * FROM messages")


def test_refresh_group_names_is_local_and_preserves_exemption(db):
    db.settings.source_account = db.settings.self_id = "account"
    cid = allow_conversation(
        db,
        "wx_cli",
        "account",
        "123@chatroom",
        "123@chatroom",
        "group",
        followup_source=False,
    )
    paths = []

    def handler(req):
        paths.append(req.url.path)
        if req.url.path.endswith("health"):
            return httpx.Response(
                200, json={"ready": True, "current_account": {"wxid": "account"}}
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "session": {
                            "username": "123@chatroom",
                            "name": "欧洲三方群 (123@chatroom)",
                        }
                    }
                ],
                "paging": {"has_more": False},
            },
        )

    app = create_app(db.settings, source_factory=lambda db: source(db, handler))
    with TestClient(app) as client:
        result = client.post(
            "/api/source/names/refresh",
            json={},
            headers={"Authorization": "Bearer " + db.token},
        )
        assert result.status_code == 200 and result.json()["updated"] == 1
    assert db.rows(
        "SELECT title,followup_source FROM conversations WHERE id=?", (cid,)
    )[0] == {"title": "欧洲三方群", "followup_source": 0}
    assert set(paths) == {"/api/v1/health", "/api/v1/sessions"}
    assert not db.rows("SELECT * FROM usage")


def test_raw_chatroom_id_is_labeled_pending_not_invented_name(db):
    db.settings.source_account = "account"
    allow_conversation(db, "wx_cli", "account", "123@chatroom", "123@chatroom", "group")
    row = list_sources(db)["items"][0]
    assert row["name_available"] is False and row["title"] == "群名待同步"
