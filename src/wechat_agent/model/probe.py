"""One explicit chat-completions compatibility probe, without customer data."""

import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..source.contracts import CapabilityReport


class ModelProbeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    model_id: str = Field(min_length=1)
    key_env: str = "DEEPSEEK_API_KEY"
    proxy_url: str | None = None
    response_mode: Literal["text", "json_object", "json_schema"] = "json_object"
    probe_output_tokens: int = Field(default=256, ge=16, le=4096)
    accepted_model_ids: list[str] = Field(default_factory=list)
    context_tokens: int | None = Field(default=None, gt=0)

    @field_validator("endpoint")
    @classmethod
    def credential_safe_endpoint(cls, value):
        urlsplit(value)
        url = httpx.URL(value)
        if url.scheme != "https" or not url.host or url.username or url.password or url.query or url.fragment:
            raise ValueError("https_endpoint_required")
        return str(url)

    @field_validator("model_id", "key_env")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("blank_model_configuration")
        return value


class ModelProbeError(Exception):
    pass


def _request(config: ModelProbeConfig) -> dict:
    payload = {
        "model": config.model_id, "stream": False, "max_tokens": config.probe_output_tokens,
        "messages": [
            {"role": "system", "content": 'Return only the JSON object {"probe":"ok"}, without explanation.'},
            {"role": "user", "content": 'Return {"probe":"ok"}.'},
        ],
    }
    if config.response_mode == "json_object":
        payload["response_format"] = {"type": "json_object"}
    elif config.response_mode == "json_schema":
        payload["response_format"] = {
            "type": "json_schema", "json_schema": {"name": "connection_probe", "strict": True,
                "schema": {"type": "object", "properties": {"probe": {"type": "string", "const": "ok"}},
                           "required": ["probe"], "additionalProperties": False}},
        }
    return payload


def _validate_response(response: httpx.Response, config: ModelProbeConfig, facts: dict) -> None:
    code = response.status_code
    if code == 401:
        raise ModelProbeError("model_authentication_failed")
    if code == 403:
        raise ModelProbeError("model_permission_denied")
    if code == 404:
        raise ModelProbeError("model_not_found")
    if code == 429:
        raise ModelProbeError("model_rate_limited")
    if 300 <= code < 400:
        raise ModelProbeError("model_redirect_refused")
    if code >= 500:
        raise ModelProbeError("model_server_error")
    if code == 400:
        try:
            error = response.json().get("error", {})
        except (ValueError, AttributeError):
            error = {}
        if isinstance(error, dict) and error.get("param") == "response_format":
            raise ModelProbeError("model_response_format_unsupported")
        raise ModelProbeError("model_request_rejected")
    if code != 200:
        raise ModelProbeError("model_request_failed")
    try:
        body = response.json()
        model = body["model"]
        choice = body["choices"][0]
        finish = choice["finish_reason"]
        content = choice["message"]["content"]
    except (ValueError, TypeError, KeyError, IndexError):
        raise ModelProbeError("model_contract_invalid") from None
    if not isinstance(model, str):
        raise ModelProbeError("model_contract_invalid")
    if model not in {config.model_id, *config.accepted_model_ids}:
        raise ModelProbeError("model_id_mismatch")
    facts["reported_model_id"] = model
    if finish == "length":
        raise ModelProbeError("model_output_truncated")
    if finish != "stop":
        raise ModelProbeError("model_unexpected_finish_reason")
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        raise ModelProbeError("model_output_invalid") from None
    if parsed != {"probe": "ok"}:
        raise ModelProbeError("model_output_invalid")
    usage = body.get("usage")
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    valid_usage = isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in keys)
    facts.update(json_output_verified=True, json_mode_accepted=config.response_mode == "json_object",
                 schema_mode_accepted=True if config.response_mode == "json_schema" else None,
                 usage={key: usage[key] for key in keys} if valid_usage else None,
                 usage_unknown=not valid_usage)


async def probe_model(config: dict, transport: httpx.AsyncBaseTransport | None = None) -> CapabilityReport:
    facts = {"scope": "minimal_connection_probe", "capacity_verified": False, "vision": "not_checked"}
    if not config:
        return CapabilityReport(component="model", status="pending", facts=facts, gaps=["model_not_configured"])
    try:
        settings = ModelProbeConfig.model_validate(config)
    except (ValueError, TypeError):
        return CapabilityReport(component="model", status="failed", facts=facts, gaps=["model_config_invalid"])
    key = os.getenv(settings.key_env)
    if not key:
        return CapabilityReport(component="model", status="pending", facts=facts, gaps=["model_key_not_configured"])
    facts.update(requested_model_id=settings.model_id, response_mode=settings.response_mode,
                 declared_context_tokens=settings.context_tokens)
    try:
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}, trust_env=False,
                                     follow_redirects=False, timeout=httpx.Timeout(300, connect=15),
                                     proxy=settings.proxy_url, transport=transport) as client:
            response = await client.post(settings.endpoint, json=_request(settings))
            _validate_response(response, settings, facts)
    except ModelProbeError as error:
        gap = str(error)
    except httpx.TimeoutException:
        gap = "model_timeout"
    except httpx.ProxyError:
        gap = "model_proxy_error"
    except httpx.RequestError:
        gap = "model_unreachable"
    except (ValueError, TypeError):
        gap = "model_config_invalid"
    else:
        return CapabilityReport(component="model", status="passed", facts=facts)
    return CapabilityReport(component="model", status="failed", facts=facts, gaps=[gap])


async def run_model_probe(config_path: Path | None) -> CapabilityReport:
    try:
        values = json.loads(config_path.read_text(encoding="utf-8")) if config_path else {}
    except (OSError, ValueError):
        return CapabilityReport(component="model", status="failed", gaps=["model_config_invalid"])
    return await probe_model(values)
