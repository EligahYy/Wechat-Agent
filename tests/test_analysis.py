import json

import httpx
import pytest

from wechat_agent.analysis import Blocked, context, reserve, run_once
from wechat_agent.ingestion import ingest
from wechat_agent.services import Conflict, accept, transition_task


def client_for(content, status=200, finish="stop", observe=None):
    def handler(req):
        if observe:
            observe(json.loads(req.content))
        return httpx.Response(
            status,
            json={
                "choices": [
                    {
                        "finish_reason": finish,
                        "message": {"content": json.dumps(content)},
                    }
                ],
                "usage": {"total_tokens": 50},
            },
        )

    return httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)
    )


def output(ref="E001"):
    return {
        "schema_version": 1,
        "suggestions": [
            {
                "kind": "task_create",
                "summary": "服务商核实附加费",
                "responsible_party": "service_provider",
                "due_text": "明天",
                "evidence_refs": [ref],
            }
        ],
    }


def test_model_evidence_accept_idempotency_and_user_version(
    db, chat, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    ingest(db, [record])
    seen = []
    client = client_for(output(), observe=seen.append)
    while run_once(db, client):
        pass
    assert "商家甲" not in json.dumps(seen, ensure_ascii=False)
    assert "13812345678" not in json.dumps(seen)
    suggestions = db.rows("SELECT * FROM suggestions")
    assert len(suggestions) == 1
    sid = suggestions[0]["id"]
    tid = accept(db, sid)
    assert accept(db, sid) == tid
    task = db.rows("SELECT * FROM tasks")[0]
    assert task["state"] == "waiting_external"
    transition_task(db, tid, "done", 1)
    with pytest.raises(Conflict):
        transition_task(db, tid, "open", 1)
    assert db.rows("SELECT * FROM tasks")[0]["state"] == "done"
    assert db.rows("SELECT SUM(actual) actual FROM usage")[0]["actual"] > 0


def test_bad_evidence_rejected_no_fact_pollution(db, chat, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    ingest(db, [record])
    run_once(db, client_for(output("E999")))
    assert not db.rows("SELECT * FROM suggestions")
    assert db.rows("SELECT * FROM jobs WHERE status='retry_wait'")


def test_forbidden_context_and_budget(db, chat, record):
    ingest(db, [record])
    with db.tx() as c:
        c.execute("UPDATE conversations SET egress=0")
    with pytest.raises(Blocked) as e:
        context(db, chat)
    assert e.value.status == "blocked_policy"
    db.settings.daily_token_limit = 10
    reserve(db, None, 8)
    with pytest.raises(Blocked):
        reserve(db, None, 3)


def test_policy_changed_while_request_running(db, chat, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    ingest(db, [record])

    def revoke(_):
        with db.tx() as c:
            c.execute("UPDATE conversations SET egress=0")

    run_once(db, client_for(output(), observe=revoke))
    assert not db.rows("SELECT * FROM suggestions")


def test_revision_invalidates_pending_not_confirmed_task(db, chat, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    ingest(db, [record])
    run_once(db, client_for(output()))
    sid = db.rows("SELECT * FROM suggestions")[0]["id"]
    ingest(db, [record | {"text": "改为下周，不要按明天处理"}])
    with pytest.raises(Conflict):
        accept(db, sid)


def test_http_auth_and_truncation_do_not_create_results(db, chat, record, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    ingest(db, [record])
    run_once(db, client_for(output(), status=401))
    assert db.rows("SELECT * FROM jobs WHERE status='blocked_credentials'")
    run_once(db, client_for(output(), finish="length"))
    assert not db.rows("SELECT * FROM suggestions")


def test_confirmed_roles_present_and_names_redacted(db, chat, record):
    ingest(db, [record])
    with db.tx() as c:
        c.execute(
            "INSERT INTO contact_roles VALUES(?,?,?,?)",
            (chat, "provider", "service_provider", "测试服务商李先生"),
        )
    _, _, payload, _ = context(db, chat)
    assert payload["messages"][0]["role"] == "service_provider"


def test_final_crashed_lease_becomes_failed(db, chat, record):
    ingest(db, [record])
    with db.tx() as c:
        c.execute(
            "UPDATE jobs SET status='running',attempts=3,lease_until='2000-01-01T00:00:00+00:00'"
        )
    assert run_once(db) is False
    assert db.rows("SELECT * FROM jobs")[0]["status"] == "failed"
