"""Read-only unified screen and exclusions independent of old CRM indexing."""

from test_workspace_queue import model
from test_workspace_queue import ready as ready

from wechat_agent.crm import configure
from wechat_agent.db import now
from wechat_agent.ingestion import ingest
from wechat_agent.workspace import queue
from wechat_agent.workspace.dashboard import snapshot
from wechat_agent.workspace.store import command, read
from wechat_agent.workspace.whitelist import change, listing


def publish(db):
    with model(db) as client:
        queue.command(db, "merchant", "start", background=False, client=client)


def test_dashboard_contact_document_job_and_followup_share_source_identity(ready):
    initial = snapshot(ready, background=False)
    assert initial["counts"]["contacts"] == 1
    assert initial["items"][0]["primary_action"]["action"] == "start"
    assert initial["followups"]["total"] == 0
    assert not ready.rows("SELECT * FROM usage")
    publish(ready)
    data = snapshot(ready, background=False)
    row = data["followups"]["items"][0]
    assert row["document_id"] and row["relationship"] == "merchant"
    assert row["status"] == "succeeded" and row["task_count"] == 1
    assert data["counts"]["tasks"] == 1
    assert data["followups"]["items"][0]["source_id"] == row["source_id"] == "merchant"
    assert data["followups"]["items"][0]["document_id"] == row["document_id"]
    calls = len(ready.rows("SELECT * FROM usage"))
    snapshot(ready, background=False)
    assert len(ready.rows("SELECT * FROM usage")) == calls


def test_person_exclusion_removes_all_screen_results_and_restores_without_reanalysis(
    ready,
):
    publish(ready)
    archived = len(ready.rows("SELECT * FROM messages"))
    calls = len(ready.rows("SELECT * FROM usage"))
    change(ready, "people", "merchant", True)
    data = snapshot(ready, background=False)
    assert data["items"] == data["followups"]["items"] == []
    assert (
        data["counts"]["contacts"]
        == data["counts"]["tasks"]
        == data["counts"]["review"]
        == 0
    )
    assert listing(ready)["items"][0]["id"] == "merchant"
    change(ready, "people", "merchant", False)
    data = snapshot(ready, background=False)
    assert data["counts"]["contacts"] == data["counts"]["tasks"] == 1
    assert len(ready.rows("SELECT * FROM messages")) == archived
    assert len(ready.rows("SELECT * FROM usage")) == calls


def test_conversation_exclusion_removes_source_people_and_recovery_preserves_archive(
    ready,
):
    publish(ready)
    cid = ready.rows("SELECT id FROM conversations WHERE source_id='chat'")[0]["id"]
    change(ready, "conversations", cid, True)
    assert snapshot(ready)["counts"]["contacts"] == 0
    assert listing(ready, "conversations")["items"][0]["id"] == cid
    assert ready.rows("SELECT COUNT(*) n FROM messages")[0]["n"] == 1
    change(ready, "conversations", cid, False)
    assert snapshot(ready)["counts"]["contacts"] == 1


def test_new_unindexed_source_can_be_excluded(ready, record):
    ingest(ready, [record | {"source_id": "new-person", "sender_id": "fresh"}])
    with ready.tx() as c:
        c.execute("DELETE FROM crm_contacts WHERE source_id='fresh'")
    assert not ready.rows("SELECT id FROM crm_contacts WHERE source_id='fresh'")
    assert snapshot(ready)["counts"]["contacts"] == 2
    change(ready, "people", "fresh", True)
    assert snapshot(ready)["counts"]["contacts"] == 1
    assert any(r["id"] == "fresh" for r in listing(ready)["items"])


def test_vertical_groups_share_fields_search_and_move_after_task_completion(
    ready, record
):
    ingest(
        ready, [record | {"source_id": "other-message", "sender_id": "other-person"}]
    )
    publish(ready)
    data = snapshot(ready, background=False)
    upper, lower = data["followups"]["items"], data["items"]
    assert len(upper) == len(lower) == 1
    assert upper[0]["source_id"] == "merchant"
    assert lower[0]["source_id"] == "other-person"
    assert set(lower[0]) <= set(upper[0])
    assert data["matched_total"] == 2
    assert snapshot(ready, q="张先生")["items"] == []
    assert snapshot(ready, q="张先生")["followups"]["total"] == 1
    assert snapshot(ready, selected="tasks")["followups"]["total"] == 1
    assert snapshot(ready, selected="tasks")["total"] == 0
    doc = read(ready, "merchant")
    aid = next(iter(doc["body"]["actions"]))
    command(ready, "merchant", doc["version"], "action", aid, "done")
    after = snapshot(ready, background=False)
    assert after["followups"]["total"] == after["counts"]["tasks"] == 0
    assert {r["source_id"] for r in after["items"]} == {"merchant", "other-person"}
    assert read(ready, "merchant")["body"]["actions"][aid]["state"] == "done"


def test_dashboard_paginates_20_search_and_filters_without_model_calls(ready, record):
    ingest(
        ready,
        [record | {"source_id": f"m-{n}", "sender_id": f"p-{n}"} for n in range(42)],
    )
    with ready.tx() as c:
        for n in range(42):
            c.execute(
                "INSERT INTO identity_metadata VALUES('account',?,?,?,'',?)",
                (f"p-{n}", f"联系人{n:02d}", f"联系人{n:02d}", now()),
            )
    first = snapshot(ready)
    second = snapshot(ready, page=2)
    last = snapshot(ready, page=999)
    assert (
        first["total"] == 43
        and len(first["items"]) == 20
        and len(second["items"]) == 20
    )
    assert last["page"] == 3 and len(last["items"]) == 3
    assert not {r["source_id"] for r in first["items"]} & {
        r["source_id"] for r in second["items"]
    }
    assert snapshot(ready, q="联系人01")["items"][0]["source_id"] == "p-1"
    assert snapshot(ready, selected="customers")["total"] == 0
    assert snapshot(ready, selected="tasks")["total"] == 0
    assert snapshot(ready, selected="unanalyzed")["total"] == 43
    assert not ready.rows("SELECT * FROM usage")


def test_dashboard_before_authorization_still_lists_contacts_but_disables_calls(ready):
    configure(ready, False)
    data = snapshot(ready, background=False)
    assert data["counts"]["contacts"] == 1
    assert data["items"][0]["primary_action"]["disabled"]
    assert not ready.rows("SELECT * FROM usage")


def test_new_history_offers_update_before_background_reconciles(ready, record):
    publish(ready)
    ingest(
        ready,
        [
            record
            | {
                "source_id": "append",
                "sender_id": "merchant",
                "text": "补充新一批需求",
                "event_time": "2026-11-10T16:00:00+08:00",
            }
        ],
    )
    data = snapshot(ready, background=False)
    row = data["items"][0]
    assert row["document_id"] and row["needs_update"]
    assert row["phase"] == "update" and row["status"] == "ready"
    assert row["primary_action"] == {
        "action": "start",
        "label": "更新分析",
        "disabled": False,
    }
    assert data["followups"]["total"] == 0


def test_dashboard_and_whitelist_api_auth_validation_and_two_navigation_entries(ready):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    client = TestClient(create_app(ready.settings))
    assert client.get("/api/workspace/dashboard").status_code == 401
    assert client.get("/api/workspace/whitelist").status_code == 401
    h = {"Authorization": "Bearer " + ready.token}
    html = client.get("/workspace", headers=h).text
    assert 'data-view="dashboard"' in html and 'data-view="settings"' in html
    for name in ("today", "customers", "review", "pilot", "scope"):
        assert f'data-view="{name}"' not in html
    assert client.get("/api/workspace/dashboard?page=0", headers=h).status_code == 422
    assert (
        client.get("/api/workspace/dashboard?selected=invalid", headers=h).status_code
        == 422
    )
    assert (
        client.get("/api/workspace/whitelist?entity=invalid", headers=h).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workspace/whitelist",
            headers=h,
            json={"entity": "people", "id": "foreign", "excluded": True},
        ).status_code
        == 422
    )
    for body in ([], {"entity": [], "id": "merchant", "excluded": True}):
        assert (
            client.post("/api/workspace/whitelist", headers=h, json=body).status_code
            == 422
        )
    assert (
        client.post(
            "/api/workspace/whitelist",
            headers=h,
            json={"entity": "people", "id": "merchant", "excluded": True},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/workspace/dashboard", headers=h).json()["counts"]["contacts"]
        == 0
    )
