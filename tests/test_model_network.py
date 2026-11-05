import errno
import json
import socket
import ssl

import httpx
import pytest

from wechat_agent.analysis import call_model
from wechat_agent.model_network import (
    connection_code,
    create_client,
    probe,
    transport_summary,
)


@pytest.mark.parametrize(
    "cause,expected",
    [
        (
            ssl.SSLCertVerificationError(1, "private certificate location"),
            "ConnectError:tls_certificate",
        ),
        (socket.gaierror(-2, "private DNS name"), "ConnectError:dns"),
        (OSError(errno.ECONNREFUSED, "private proxy address"), "ConnectError:refused"),
        (OSError(errno.ENETUNREACH, "private network"), "ConnectError:unreachable"),
    ],
)
def test_connection_causes_are_classified_without_printing_details(cause, expected):
    error = httpx.ConnectError("http://user:password@private-proxy")
    error.__cause__ = cause
    assert connection_code(error) == expected
    assert "private" not in connection_code(
        error
    ) and "password" not in connection_code(error)


def test_explicit_model_proxy_preserves_tls_verification(monkeypatch):
    import certifi

    seen = {}
    monkeypatch.setenv("DEEPSEEK_PROXY", "http://user:password@127.0.0.1:7890")
    monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
    monkeypatch.setattr(
        "wechat_agent.model_network.httpx.Client", lambda **kw: seen.update(kw)
    )
    create_client()
    assert seen["proxy"] == "http://user:password@127.0.0.1:7890"
    assert seen["trust_env"] is False
    assert (
        seen["verify"].verify_mode == ssl.CERT_REQUIRED
        and seen["verify"].check_hostname
    )
    report = json.dumps(transport_summary())
    assert "password" not in report and "7890" not in report and "certifi" not in report


def test_probe_has_no_key_no_chat_and_makes_no_inference_call(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-send")

    def handler(req):
        assert req.method == "GET" and req.url.path == "/models"
        assert "authorization" not in req.headers and not req.content
        return httpx.Response(401)

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)
    ) as client:
        result = probe(client)
    assert (
        result["connected"]
        and result["http_status"] == 401
        and result["inference_called"] is False
    )


def test_proxy_connection_failure_has_no_reserved_usage(db, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    def handler(req):
        raise httpx.ProxyError("private proxy password", request=req)

    with httpx.Client(
        base_url="https://api.deepseek.com", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(httpx.ProxyError):
            call_model(db, {"messages": []}, client=client)
    assert db.rows("SELECT actual,status FROM usage") == [
        {"actual": 0, "status": "request_rejected"}
    ]


def test_invalid_transport_configuration_does_not_reserve_tokens(db, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_PROXY", "socks5://127.0.0.1:7890")
    with pytest.raises(ValueError, match="model_proxy_configuration"):
        call_model(db, {"messages": []})
    assert not db.rows("SELECT * FROM usage")
