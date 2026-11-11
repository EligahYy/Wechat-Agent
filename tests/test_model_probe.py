"""Minimal model connection checks; synthetic HTTP, no paid calls."""

import json

import httpx
import pytest
from pydantic import ValidationError


def config():
    return {"endpoint": "https://api.deepseek.com/chat/completions", "model_id": "configured-test-model",
            "key_env": "MODEL_TEST_KEY"}


def completion(*, model="configured-test-model", content='{"probe":"ok"}', finish="stop", usage=True):
    body = {"model": model, "choices": [{"index": 0, "finish_reason": finish,
             "message": {"role": "assistant", "content": content, "reasoning_content": "must not export reasoning"}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}
    return body


@pytest.mark.asyncio
async def test_missing_model_config_stays_pending():
    from wechat_agent.model.probe import probe_model
    def forbidden(_):
        raise AssertionError("No request permitted")
    result = await probe_model({}, transport=httpx.MockTransport(forbidden))
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_missing_credentials_do_not_call_network(monkeypatch):
    from wechat_agent.model.probe import probe_model
    monkeypatch.delenv("MODEL_TEST_KEY", raising=False)
    result = await probe_model(config(), transport=httpx.MockTransport(lambda _: pytest.fail("No request permitted")))
    assert result.status == "pending"
    assert "model_key_not_configured" in result.gaps


@pytest.mark.asyncio
async def test_valid_probe_preserves_usage_without_claiming_capacity_or_vision(monkeypatch):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    calls = []
    def respond(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer private-api-key"
        payload = json.loads(request.content)
        assert payload["model"] == "configured-test-model"
        assert payload["stream"] is False
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 256
        return httpx.Response(200, json=completion())
    result = await probe_model(config(), transport=httpx.MockTransport(respond))
    assert result.status == "passed"
    assert len(calls) == 1
    assert result.facts["usage"]["total_tokens"] == 17
    assert result.facts["capacity_verified"] is False
    assert result.facts["vision"] == "not_checked"
    assert "private-api-key" not in result.model_dump_json()
    assert "must not export reasoning" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,gap", [
    (401, {"error": {"message": "private-api-key"}}, "model_authentication_failed"),
    (403, {}, "model_permission_denied"),
    (404, {}, "model_not_found"),
    (429, {}, "model_rate_limited"),
    (500, {}, "model_server_error"),
    (302, {}, "model_redirect_refused"),
    (400, {"error": {"param": "response_format"}}, "model_response_format_unsupported"),
    (200, completion(model="unexpected-model"), "model_id_mismatch"),
    (200, completion(model="private-api-key"), "model_id_mismatch"),
    (200, completion(finish="length"), "model_output_truncated"),
    (200, completion(content="not JSON"), "model_output_invalid"),
    (200, completion(content='{"probe":"wrong"}'), "model_output_invalid"),
    (200, {}, "model_contract_invalid"),
])
async def test_failures_are_classified_and_not_retried(monkeypatch, status, body, gap):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    result = await probe_model(config(), transport=httpx.MockTransport(respond))
    assert result.status != "passed"
    assert gap in result.gaps
    assert len(calls) == 1
    assert "private-api-key" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_aliases_must_be_explicit(monkeypatch):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    settings = {**config(), "accepted_model_ids": ["verified-alias"]}
    result = await probe_model(settings, transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=completion(model="verified-alias", usage=False))))
    assert result.status == "passed"
    assert result.facts["usage_unknown"] is True
    assert result.facts["usage"] is None


@pytest.mark.asyncio
async def test_declared_capacity_is_not_verified_by_short_probe(monkeypatch):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    result = await probe_model({**config(), "context_tokens": 32000},
                              transport=httpx.MockTransport(lambda _: httpx.Response(200, json=completion())))
    assert result.status == "passed"
    assert result.facts["declared_context_tokens"] == 32000
    assert result.facts["capacity_verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["http://example.com/chat", "https://user:password@example.com/chat", "https://[", "https://example.com/chat?key=private"])
async def test_invalid_endpoint_does_not_send_key(monkeypatch, endpoint):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    result = await probe_model({**config(), "endpoint": endpoint},
                              transport=httpx.MockTransport(lambda _: pytest.fail("No request permitted")))
    assert result.status == "failed"
    assert "model_config_invalid" in result.gaps


@pytest.mark.asyncio
async def test_timeout_is_not_fake_success(monkeypatch):
    from wechat_agent.model.probe import probe_model
    monkeypatch.setenv("MODEL_TEST_KEY", "private-api-key")
    def timeout(request):
        raise httpx.ReadTimeout("private-api-key", request=request)
    result = await probe_model(config(), transport=httpx.MockTransport(timeout))
    assert result.status == "failed"
    assert "model_timeout" in result.gaps
    assert "private-api-key" not in result.model_dump_json()


def test_verified_capability_contract_rejects_impossible_limits():
    from datetime import datetime, timezone
    from wechat_agent.model.contracts import ModelCapabilities
    with pytest.raises(ValidationError):
        ModelCapabilities(model_id="test", context_tokens=10, max_output_tokens=20,
                          structured_output=False, vision=False, verified_at=datetime.now(timezone.utc))


def test_cli_model_check_does_not_connect_without_config(tmp_path, monkeypatch):
    from wechat_agent.doctor import main
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "model.json"
    assert main(["--check-model", "--output", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["model"]["status"] == "pending"
    assert "model_not_configured" in result["model"]["gaps"]
