"""wx-cli protocol checks use synthetic data from the upstream v0.7.4 schema."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError


def health(account="account-a", ready=True):
    value = json.loads((Path(__file__).parent / "fixtures/source-probe.json").read_text())["health"]
    value["ready"] = ready
    value["current_account"]["wxid"] = account
    return value


def envelope(items, *, offset=0, limit=2, total=None, skipped=0, warnings=None):
    total = len(items) if total is None else total
    return {"items": items,
            "paging": {"limit": limit, "offset": offset, "returned": len(items),
                       "has_more": offset + limit < total, "total": total},
            "stats": {"scanned": total, "skipped": skipped, "shard_warnings": warnings or []}}


def message(server_id=1, *, sender="merchant-a", talker="merchant-a", content=None):
    return {"sort_seq": server_id, "server_id": server_id, "msg_type": 1, "sub_type": 0,
            "sender": sender, "talker": talker, "create_time": 1794366000,
            "content": content or {"Text": "Synthetic text"}, "status": 0,
            "sender_display_name": "Same name", "direction": "incoming", "snippet": "truncated"}


def test_no_sender_mapping_cannot_pass():
    from wechat_agent.source.probe import normalize_probe
    result = normalize_probe({"messages": [{"body": "已发出"}]}, mapping={})
    assert result.status != "passed"
    assert "sender_mapping_missing" in result.gaps


def test_capture_validation_is_not_full_history_verification():
    from wechat_agent.source.probe import normalize_probe, WX_MESSAGE_MAPPING
    result = normalize_probe({"account_id": "account-a", **envelope([message()])}, WX_MESSAGE_MAPPING)
    assert result.status == "passed"
    assert result.facts["messages_valid"] == 1
    assert result.facts["history_complete"] is False
    assert result.facts["live_connection_verified"] is False


def test_partial_shard_is_reported_as_gap():
    from wechat_agent.source.probe import normalize_probe, WX_MESSAGE_MAPPING
    result = normalize_probe({"account_id": "account-a", **envelope([message()], skipped=1)}, WX_MESSAGE_MAPPING)
    assert result.status == "pending"
    assert "source_rows_skipped" in result.gaps


def test_missing_sender_does_not_get_replaced_by_display_name():
    from wechat_agent.source.probe import normalize_probe, WX_MESSAGE_MAPPING
    result = normalize_probe({"account_id": "account-a", **envelope([message(sender="")])}, WX_MESSAGE_MAPPING)
    assert result.status != "passed"
    assert "message_sender_missing" in result.gaps


def test_contacts_keep_identity_separate_from_alias():
    from wechat_agent.source.contracts import ContactKey, ContactRecord
    a = ContactRecord(key=ContactKey(account_id="a", contact_id="one"), remark="Same", nickname=None, is_self=False)
    b = ContactRecord(key=ContactKey(account_id="a", contact_id="two"), remark="Same", nickname=None, is_self=False)
    renamed = a.model_copy(update={"remark": "Changed"})
    assert a.key != b.key
    assert a.key == renamed.key
    assert a.key != ContactKey(account_id="b", contact_id="one")


def test_group_is_a_conversation_not_a_contact():
    from wechat_agent.source.contracts import ContactKey, ConversationRecord
    with pytest.raises(ValidationError):
        ContactKey(account_id="a", contact_id="room@chatroom")
    assert ConversationRecord(account_id="a", conversation_id="room@chatroom", kind="group",
                              title=None, member_ids=[]).kind == "group"


def test_page_rejects_mixed_conversations_and_accounts():
    from wechat_agent.source.contracts import SourcePage
    from wechat_agent.source.wx_cli import parse_message
    item = parse_message(message(talker="other"), "account-a")
    with pytest.raises(ValidationError):
        SourcePage(account_id="account-a", conversation_id="one", records=[item],
                   next_cursor=None, complete=True, gaps=[])


def test_message_uses_full_content_and_sender_stable_id():
    from wechat_agent.source.wx_cli import parse_message
    parsed = parse_message(message(content={"Text": "full text that snippet omits"}), "account-a")
    assert parsed.body == "full text that snippet omits"
    assert parsed.sender_id == "merchant-a"
    assert parsed.sent_at.utcoffset().total_seconds() == 0
    assert parsed.message_id != parse_message(message(talker="other"), "account-a").message_id


def test_zero_message_id_is_not_hash_deduplicated():
    from wechat_agent.source.wx_cli import parse_message
    with pytest.raises(ValueError, match="message_id_unavailable"):
        parse_message(message(server_id=0), "account-a")


def test_quote_and_file_metadata_are_preserved():
    from wechat_agent.source.wx_cli import parse_message
    raw = message(content={"Quote": {"reply_text": "新一批", "refer_sender": "other", "refer_content": "旧批"}})
    raw.update(msg_type=49, sub_type=57)
    parsed = parse_message(raw, "account-a")
    assert parsed.kind == "quote"
    assert parsed.body == "新一批"
    assert parsed.raw["content"]["Quote"]["refer_content"] == "旧批"
    raw.update(sub_type=6, content={"File": {"title": "packing.xlsx", "raw_xml": "<file/>"}})
    assert parse_message(raw, "account-a").attachment_ids


@pytest.mark.asyncio
async def test_health_only_never_reads_chat_and_bypasses_proxy(tmp_path, monkeypatch):
    from wechat_agent.source.probe import run_source_probe
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    calls = []
    def respond(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=health())
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"expected_account_id": "account-a"}))
    result = await run_source_probe(config, transport=httpx.MockTransport(respond))
    assert result.status == "passed"
    assert calls == [("GET", "/api/v1/health")]
    assert result.facts["scope"] == "connection"
    assert result.facts["history_complete"] is False
    assert "account-a" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_unpinned_account_and_wrong_account_do_not_read_samples(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    calls = []
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=health())
    config = tmp_path / "source.json"
    config.write_text(json.dumps({}))
    result = await run_source_probe(config, samples=True, transport=httpx.MockTransport(respond))
    assert result.status == "pending"
    assert "source_account_not_pinned" in result.gaps
    config.write_text(json.dumps({"expected_account_id": "other-account"}))
    result = await run_source_probe(config, samples=True, transport=httpx.MockTransport(respond))
    assert result.status == "failed"
    assert "source_account_mismatch" in result.gaps
    assert calls == ["/api/v1/health", "/api/v1/health"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,gap", [
    (401, {"error": "unauthorized"}, "source_authentication_failed"),
    (200, {"ready": True}, "source_contract_invalid"),
    (200, health(ready=False), "source_not_ready"),
    (302, {}, "source_redirect_refused"),
    (500, {}, "source_server_error"),
])
async def test_failures_are_not_no_new_messages(tmp_path, status, body, gap):
    from wechat_agent.source.probe import run_source_probe
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"expected_account_id": "account-a"}))
    result = await run_source_probe(config, transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)))
    assert result.status != "passed"
    assert gap in result.gaps


@pytest.mark.asyncio
async def test_non_loopback_url_is_refused_without_request(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"base_url": "http://example.com:9100"}))
    def forbidden(_):
        raise AssertionError("No request permitted")
    result = await run_source_probe(config, transport=httpx.MockTransport(forbidden))
    assert result.status == "failed"
    assert "source_config_invalid" in result.gaps


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://[", "http://user:password@localhost:9100", "http://127.0.0.1:9100?token=private"])
async def test_malformed_or_credential_url_returns_safe_error(tmp_path, url):
    from wechat_agent.source.probe import run_source_probe
    result = await run_source_probe(None, base_url=url)
    assert result.status == "failed"
    assert "source_config_invalid" in result.gaps
    assert "private" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_timeout_is_classified(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    def timeout(request):
        raise httpx.ConnectTimeout("local endpoint unavailable", request=request)
    result = await run_source_probe(None, transport=httpx.MockTransport(timeout))
    assert result.status == "failed"
    assert "source_timeout" in result.gaps


@pytest.mark.asyncio
async def test_sample_pages_keep_read_scope_and_do_not_dump_messages(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    calls = []
    def respond(request):
        calls.append(request)
        path = request.url.path
        if path == "/api/v1/health":
            return httpx.Response(200, json=health())
        assert request.url.params["show_hidden"] == "1"
        if path == "/api/v1/contacts":
            return httpx.Response(200, json=envelope([
                {"user_name": "merchant-a", "nick_name": "Same", "remark": ""},
                {"user_name": "merchant-b", "nick_name": "Same", "remark": ""},
                {"user_name": "room@chatroom", "nick_name": "Room", "remark": ""}], limit=20))
        if path == "/api/v1/sessions":
            return httpx.Response(200, json=envelope([
                {"username": "merchant-a", "display_name": "Same"},
                {"username": "room@chatroom", "display_name": "Room"}], limit=20))
        assert path == "/api/v1/messages"
        talker = request.url.params["contact"]
        offset = int(request.url.params["offset"])
        rows = [message(i, talker=talker) for i in range(offset + 1, min(offset + 3, 4))]
        return httpx.Response(200, json=envelope(rows, offset=offset, total=3))
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"expected_account_id": "account-a"}))
    result = await run_source_probe(config, samples=True, transport=httpx.MockTransport(respond))
    assert result.status == "passed"
    assert result.facts["contacts_checked"] == 2
    assert result.facts["groups_checked"] == 1
    assert result.facts["message_pages_checked"] == 4
    assert result.facts["messages_checked"] == 6
    assert result.facts["history_complete"] is False
    assert "Synthetic text" not in result.model_dump_json()
    assert all(r.method == "GET" for r in calls)


@pytest.mark.asyncio
async def test_credentials_and_server_errors_are_not_exposed(tmp_path, monkeypatch):
    from wechat_agent.source.probe import run_source_probe
    monkeypatch.setenv("WX_TEST_TOKEN", "sensitive-source-token")
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"token_env": "WX_TEST_TOKEN"}))
    def respond(request):
        assert request.headers["Authorization"] == "Bearer sensitive-source-token"
        return httpx.Response(500, text="sensitive-source-token and private body")
    result = await run_source_probe(config, transport=httpx.MockTransport(respond))
    assert "sensitive-source-token" not in result.model_dump_json()
    assert "private body" not in result.model_dump_json()


def test_cli_source_check_reports_missing_service_without_calling_model(tmp_path):
    from wechat_agent.doctor import main
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"base_url": "http://127.0.0.1:1"}))
    output = tmp_path / "report.json"
    assert main(["--check-source", "--source-config", str(config), "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["source"]["status"] == "failed"
    assert report["model"]["status"] == "pending"


def test_malformed_capture_returns_diagnostic_without_private_input():
    from wechat_agent.source.probe import normalize_probe, WX_MESSAGE_MAPPING
    result = normalize_probe({"account_id": "private-account", "items": "private-value"}, WX_MESSAGE_MAPPING)
    assert result.status == "failed"
    assert "source_contract_invalid" in result.gaps
    assert "private-value" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_message_scope_mismatch_stops_sample(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    def respond(request):
        if request.url.path.endswith("health"):
            return httpx.Response(200, json=health())
        if request.url.path.endswith("contacts"):
            return httpx.Response(200, json=envelope([]))
        if request.url.path.endswith("sessions"):
            return httpx.Response(200, json=envelope([{"username": "merchant-a"}]))
        return httpx.Response(200, json=envelope([message(talker="other-person")]))
    config = tmp_path / "source.json"
    config.write_text(json.dumps({"expected_account_id": "account-a"}))
    result = await run_source_probe(config, samples=True, transport=httpx.MockTransport(respond))
    assert result.status == "failed"
    assert "source_message_scope_mismatch" in result.gaps


@pytest.mark.asyncio
async def test_empty_message_samples_do_not_verify_message_contract(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    def respond(request):
        if request.url.path.endswith("health"):
            return httpx.Response(200, json=health())
        if request.url.path.endswith("sessions"):
            return httpx.Response(200, json=envelope([{"username": "merchant-a"}, {"username": "room@chatroom"}]))
        return httpx.Response(200, json=envelope([]))
    result = await run_source_probe(None, expected_account_id="account-a", samples=True,
                                    transport=httpx.MockTransport(respond))
    assert result.status == "pending"
    assert "source_private_messages_unavailable" in result.gaps
    assert "source_group_messages_unavailable" in result.gaps


@pytest.mark.asyncio
async def test_account_switch_during_sample_is_rejected(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    health_calls = 0
    def respond(request):
        nonlocal health_calls
        if request.url.path.endswith("health"):
            health_calls += 1
            return httpx.Response(200, json=health(account="account-a" if health_calls == 1 else "switched-account"))
        return httpx.Response(200, json=envelope([]))
    result = await run_source_probe(None, expected_account_id="account-a", samples=True,
                                    transport=httpx.MockTransport(respond))
    assert result.status == "failed"
    assert "source_changed_during_probe" in result.gaps


@pytest.mark.asyncio
async def test_schema_errors_explain_fields_without_echoing_values(tmp_path):
    from wechat_agent.source.probe import run_source_probe
    result = await run_source_probe(None, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"ready": "private-wrong-value"})))
    assert result.status == "failed"
    assert any(item["path"] == "ready" for item in result.facts["schema_errors"])
    assert "private-wrong-value" not in result.model_dump_json()
