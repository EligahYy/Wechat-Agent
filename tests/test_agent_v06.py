import httpx
import pytest
from test_crm import model, response, setup_work_chat

from wechat_agent.analysis import call_model, context, run_once
from wechat_agent.collector import Collector
from wechat_agent.crm import configure, index_contacts, overview
from wechat_agent.identity import save_display, set_excluded, sync_contacts


def test_source_names_enrich_existing_contacts_without_model_calls(db, record):
    cid, _ = setup_work_chat(db, record, kind="group")
    save_display(db, "account", "merchant", "欧洲商家张总 (merchant)")
    with db.tx() as c:
        index_contacts(c, "account")
    assert db.rows("SELECT name FROM crm_contacts")[0]["name"] == "欧洲商家张总"
    assert not db.rows("SELECT * FROM usage")
    _, _, payload, _ = context_after_authorizing(db, cid)
    assert "欧洲商家张总" not in str(payload)


def context_after_authorizing(db, cid):
    configure(db, True)
    return context(db, cid)


def test_response_replay_does_not_repeat_billing(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    cid, _ = setup_work_chat(db, record)
    _, _, payload, _ = context_after_authorizing(db, cid)
    calls = []
    client = model(response(db), calls.append)
    first = call_model(db, payload, client=client)
    second = call_model(db, payload, client=client)
    assert first == second and len(calls) == 1
    assert len(db.rows("SELECT * FROM usage")) == 1
    assert len(db.rows("SELECT * FROM model_responses")) == 1


@pytest.mark.parametrize("kind", ["provider", "internal", "buyer", "announcement"])
def test_non_merchant_conversation_cannot_create_customer(
    db, record, monkeypatch, kind
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    setup_work_chat(db, record)
    configure(db, True)
    result = response(db) | {"conversation_type": kind}
    assert run_once(db, model(result))
    assert not db.rows("SELECT * FROM crm_customers")
    assert not db.rows("SELECT * FROM crm_actions")


def test_excluded_person_still_allows_other_group_members(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    setup_work_chat(db, record, kind="group")
    configure(db, True)
    actor = db.rows("SELECT id FROM crm_contacts")[0]["id"]
    set_excluded(db, actor, True, "同事")
    run_once(db, model(response(db)))
    assert not db.rows("SELECT * FROM crm_customers")
    assert (
        db.rows("SELECT followup_source FROM conversations")[0]["followup_source"] == 1
    )


def test_shipment_event_stops_same_batch_request(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    _, row = setup_work_chat(db, record)
    from wechat_agent.ingestion import ingest

    ingest(db, [row | {"text": "这批货已经发货了"}])
    configure(db, True)
    value = response(db)
    value["business_events"] = [
        {
            "customer_ref": value["people"][0]["actor_ref"],
            "opportunity": value["actions"][0]["opportunity"],
            "kind": "shipment_reported",
            "evidence_refs": ["E001"],
        }
    ]
    run_once(db, model(value))
    assert len(db.rows("SELECT * FROM business_events")) == 1
    assert not db.rows("SELECT * FROM crm_actions")


def test_followup_required_false_does_not_manufacture_task(db, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic")
    setup_work_chat(db, record)
    configure(db, True)
    value = response(db)
    value["actions"][0]["followup_required"] = False
    run_once(db, model(value))
    assert db.rows("SELECT * FROM crm_customers")
    assert not overview(db)["all_actions"]


def test_contacts_sync_atomically_uses_account_and_paging(db, record):
    setup_work_chat(db, record)

    def handler(req):
        if req.url.path.endswith("health"):
            return httpx.Response(
                200,
                json={
                    "ready": True,
                    "current_account": {"wxid": "account", "name": "测试"},
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "user_name": "merchant",
                        "remark": "微信备注",
                        "nick_name": "张先生",
                        "alias": "zhang",
                    }
                ],
                "paging": {"has_more": False},
            },
        )

    source = Collector(
        db,
        httpx.Client(
            base_url="http://127.0.0.1:9100", transport=httpx.MockTransport(handler)
        ),
    )
    assert sync_contacts(db, source)["contacts"] == 1
    assert db.rows("SELECT remark FROM identity_metadata")[0]["remark"] == "微信备注"


def test_scope_undo_restores_egress_and_refuses_second_undo(db, record):
    from wechat_agent.source_scope import set_sources, undo_sources

    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    with db.tx() as c:
        c.execute("UPDATE conversations SET egress=0 WHERE id=?", (cid,))
    op = set_sources(db, [cid], False)
    undo_sources(db, op["undo_id"])
    assert db.rows(
        "SELECT followup_source,egress FROM conversations WHERE id=?", (cid,)
    )[0] == {"followup_source": 1, "egress": 0}
    with pytest.raises(ValueError):
        undo_sources(db, op["undo_id"])


def test_scope_undo_refuses_intervening_policy_change(db, record):
    from wechat_agent.source_scope import set_sources, undo_sources

    cid, _ = setup_work_chat(db, record)
    configure(db, True)
    op = set_sources(db, [cid], False)
    set_sources(db, [cid], True)
    with pytest.raises(ValueError):
        undo_sources(db, op["undo_id"])
