"""Shared, verified model transport and token-free connectivity diagnostics."""

import errno
import os
import socket
import ssl
from urllib.parse import urlparse
from urllib.request import getproxies

import certifi
import httpx

ENDPOINT = "https://api.deepseek.com"


def connection_code(exc):
    chain, seen = [], set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    # Inspect internally, but never return exception strings: they may contain
    # proxy credentials, request URLs, local certificate paths or network names.
    descriptions = " ".join(str(e).lower() for e in chain)
    if (
        any(isinstance(e, ssl.SSLCertVerificationError) for e in chain)
        or "certificate_verify_failed" in descriptions
        or "certificate verify failed" in descriptions
    ):
        return "ConnectError:tls_certificate"
    if any(isinstance(e, socket.gaierror) for e in chain) or any(
        s in descriptions
        for s in (
            "nodename nor servname",
            "name or service not known",
            "getaddrinfo failed",
            "temporary failure in name resolution",
        )
    ):
        return "ConnectError:dns"
    if (
        any(getattr(e, "errno", None) == errno.ECONNREFUSED for e in chain)
        or "connection refused" in descriptions
    ):
        return "ConnectError:refused"
    if any(
        getattr(e, "errno", None) in {errno.ENETUNREACH, errno.EHOSTUNREACH}
        for e in chain
    ) or any(s in descriptions for s in ("network is unreachable", "no route to host")):
        return "ConnectError:unreachable"
    if isinstance(exc, httpx.ProxyError):
        return "ProxyError"
    if isinstance(exc, httpx.ConnectTimeout):
        return "ConnectTimeout"
    return "ConnectError"


def transport_summary():
    route = os.environ.get("DEEPSEEK_PROXY", "").strip()
    proxies = getproxies()
    return {
        "endpoint": ENDPOINT,
        "route": "direct"
        if route == "direct"
        else "explicit_http_proxy"
        if route
        else "system_or_environment",
        "proxy_detected": bool(route and route != "direct")
        or (not route and any(bool(proxies.get(k)) for k in ("http", "https", "all"))),
        "custom_ca_configured": bool(
            os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")
        ),
        "tls_verification": True,
    }


def create_client():
    route = os.environ.get("DEEPSEEK_PROXY", "").strip()
    options = {
        "base_url": ENDPOINT,
        "timeout": httpx.Timeout(90, connect=10),
        "follow_redirects": False,
    }
    if route:
        # Explicit routing is opt-in. Never auto-bypass an existing proxy or
        # retry a failed request over a different route.
        options["trust_env"] = False
        if route != "direct":
            parsed = urlparse(route)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("model_proxy_configuration")
            options["proxy"] = route
        try:
            options["verify"] = ssl.create_default_context(
                cafile=os.environ.get("SSL_CERT_FILE") or certifi.where(),
                capath=os.environ.get("SSL_CERT_DIR") or None,
            )
        except (OSError, ssl.SSLError):
            raise ValueError("model_ca_configuration") from None
    try:
        return httpx.Client(**options)
    except ImportError:
        raise ValueError("model_proxy_configuration") from None
    except (OSError, ssl.SSLError, ValueError):
        raise ValueError("model_transport_configuration") from None


def probe(client=None):
    """GET /models without an API key or chat; no inference call is made."""
    own = client is None
    transport = transport_summary()
    try:
        client = client or create_client()
        # Same proxy and CA rules as analysis, but no Authorization header.
        response = client.get("/models", timeout=httpx.Timeout(15, connect=10))
        return transport | {
            "connected": True,
            "http_status": response.status_code,
            "inference_called": False,
            "notice": "收到HTTP响应说明连接已建立；401在此无key自检中属正常，不代表已验证账户权限。",
        }
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError) as exc:
        return transport | {
            "connected": False,
            "error": connection_code(exc),
            "inference_called": False,
        }
    except httpx.HTTPError as exc:
        return transport | {
            "connected": False,
            "error": type(exc).__name__,
            "inference_called": False,
        }
    except ValueError as exc:
        return transport | {
            "connected": False,
            "error": str(exc)
            if str(exc)
            in {
                "model_proxy_configuration",
                "model_ca_configuration",
                "model_transport_configuration",
            }
            else "model_transport_configuration",
            "inference_called": False,
        }
    finally:
        if own and client is not None:
            client.close()
