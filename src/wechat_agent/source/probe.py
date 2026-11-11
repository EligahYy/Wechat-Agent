"""Bounded GET diagnostics; no model requests, source writes or service lifecycle actions."""

import hashlib
import json
import os
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .contracts import CapabilityReport, ContactKey, ContactRecord
from .wx_cli import Envelope, Health, parse_message


WX_MESSAGE_MAPPING = {"sender_id": "sender", "message_id": "server_id", "conversation_id": "talker", "sent_at": "create_time"}


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "http://127.0.0.1:9100"
    expected_account_id: str | None = None
    token_env: str | None = None
    timeout_seconds: float = Field(default=5, gt=0, le=30)

    @field_validator("base_url")
    @classmethod
    def loopback_only(cls, value):
        url = httpx.URL(value)
        if (url.scheme not in {"http", "https"} or url.host not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("loopback_source_required")
        return str(url).rstrip("/")


class ProbeError(Exception):
    pass


def _schema_errors(error: ValidationError) -> list[dict]:
    return [{"path": ".".join(map(str, item["loc"])), "type": item["type"]}
            for item in error.errors(include_input=False, include_url=False, include_context=False)]


async def _get(client: httpx.AsyncClient, path: str, params=None) -> dict:
    response = await client.get(path, params=params)
    if response.status_code == 401:
        raise ProbeError("source_authentication_failed")
    if 300 <= response.status_code < 400:
        raise ProbeError("source_redirect_refused")
    if response.status_code >= 500:
        raise ProbeError("source_server_error")
    if response.status_code != 200:
        raise ProbeError("source_request_failed")
    try:
        value = response.json()
    except ValueError:
        raise ProbeError("source_contract_invalid") from None
    if not isinstance(value, dict):
        raise ProbeError("source_contract_invalid")
    return value


def normalize_probe(raw: dict, mapping: dict) -> CapabilityReport:
    gaps = []
    for key, wire_key in WX_MESSAGE_MAPPING.items():
        if mapping.get(key) != wire_key:
            gaps.append({"sender_id": "sender_mapping_missing", "message_id": "message_id_mapping_missing",
                         "conversation_id": "conversation_mapping_missing", "sent_at": "timestamp_mapping_missing"}[key])
    account = raw.get("account_id")
    if not isinstance(account, str) or not account.strip():
        gaps.append("source_account_missing")
    facts = {"scope": "capture_validation", "history_complete": False, "live_connection_verified": False,
             "messages_valid": 0}
    if gaps:
        return CapabilityReport(component="source_capture", status="pending", facts=facts, gaps=gaps)
    try:
        page = Envelope.model_validate({k: raw.get(k) for k in ("items", "paging", "stats")})
    except ValidationError as error:
        facts["schema_errors"] = _schema_errors(error)
        return CapabilityReport(component="source_capture", status="failed", facts=facts, gaps=["source_contract_invalid"])
    if page.stats.skipped:
        gaps.append("source_rows_skipped")
    if page.stats.shard_warnings:
        gaps.append("source_shards_unavailable")
    for row in page.items:
        if not isinstance(row.get("sender"), str) or not row["sender"].strip():
            gaps.append("message_sender_missing")
            continue
        try:
            parse_message(row, account)
        except (ValueError, OverflowError, OSError):
            gaps.append("message_contract_invalid")
        else:
            facts["messages_valid"] += 1
    facts["sample_has_more"] = page.paging.has_more
    return CapabilityReport(component="source_capture", status="pending" if gaps else "passed",
                            facts=facts, gaps=sorted(set(gaps)))


async def _samples(client: httpx.AsyncClient, initial: Health, facts: dict) -> list[str]:
    params = {"limit": 20, "offset": 0, "show_hidden": "1"}
    contacts = Envelope.model_validate(await _get(client, "/api/v1/contacts", params))
    sessions = Envelope.model_validate(await _get(client, "/api/v1/sessions", params))
    account = initial.current_account.wxid
    gaps = []
    people = set()
    groups = set()
    for row in contacts.items:
        identifier = row.get("user_name")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ProbeError("source_contact_identity_missing")
        if identifier.endswith("@chatroom"):
            groups.add(identifier)
            continue
        person = ContactRecord(key=ContactKey(account_id=account, contact_id=identifier),
                               remark=row.get("remark") or None, nickname=row.get("nick_name") or None,
                               is_self=identifier == account)
        people.add(person.key)
        if not person.remark and not person.nickname:
            gaps.append("source_contact_names_missing")
    targets = {}
    for row in sessions.items:
        identifier = row.get("username")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ProbeError("source_conversation_identity_missing")
        kind = "group" if identifier.endswith("@chatroom") else "private"
        targets.setdefault(kind, identifier)
        if kind == "group":
            groups.add(identifier)
    facts.update(contacts_checked=len(people), groups_checked=len(groups),
                 message_pages_checked=0, messages_checked=0)
    for kind in ("private", "group"):
        if kind not in targets:
            gaps.append(f"source_{kind}_sample_unavailable")
            continue
        offset = 0
        kind_messages = 0
        for _ in range(2):
            raw = await _get(client, "/api/v1/messages",
                             {"contact": targets[kind], "limit": 2, "offset": offset, "order": "asc", "show_hidden": "1"})
            page = Envelope.model_validate(raw)
            if page.paging.offset != offset or page.paging.limit != 2:
                raise ProbeError("source_pagination_mismatch")
            if any(row.get("talker") != targets[kind] for row in page.items):
                raise ProbeError("source_message_scope_mismatch")
            normalized = normalize_probe({"account_id": account, **raw}, WX_MESSAGE_MAPPING)
            gaps.extend(normalized.gaps)
            facts["message_pages_checked"] += 1
            facts["messages_checked"] += normalized.facts["messages_valid"]
            kind_messages += normalized.facts["messages_valid"]
            if not page.items and page.paging.has_more:
                gaps.append("source_empty_page_with_more")
            if not page.paging.has_more:
                break
            offset += page.paging.limit
        if not kind_messages:
            gaps.append(f"source_{kind}_messages_unavailable")
    for page in (contacts, sessions):
        if page.stats.skipped or page.stats.shard_warnings:
            gaps.append("source_metadata_partial")
    final = Health.model_validate(await _get(client, "/api/v1/health"))
    if final.current_account.wxid != account or final.worker_id != initial.worker_id:
        raise ProbeError("source_changed_during_probe")
    if not final.ready:
        raise ProbeError("source_not_ready")
    return sorted(set(gaps))


async def run_source_probe(config_path: Path | None, *, transport: httpx.AsyncBaseTransport | None = None,
                           samples: bool = False, base_url: str | None = None,
                           expected_account_id: str | None = None) -> CapabilityReport:
    facts = {"scope": "sample" if samples else "connection", "history_complete": False}
    try:
        values = json.loads(config_path.read_text(encoding="utf-8")) if config_path else {}
        if base_url is not None:
            values["base_url"] = base_url
        if expected_account_id is not None:
            values["expected_account_id"] = expected_account_id
        config = SourceConfig.model_validate(values)
    except (OSError, ValueError, TypeError):
        return CapabilityReport(component="source", status="failed", facts=facts, gaps=["source_config_invalid"])
    facts["base_url"] = config.base_url
    headers = {}
    if config.token_env:
        token = os.getenv(config.token_env)
        if not token:
            return CapabilityReport(component="source", status="pending", facts=facts, gaps=["source_token_not_configured"])
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(base_url=config.base_url, headers=headers, trust_env=False,
                                     follow_redirects=False, timeout=config.timeout_seconds, transport=transport) as client:
            active = Health.model_validate(await _get(client, "/api/v1/health"))
            facts.update(ready=active.ready, cli_version=active.cli_version,
                         account_fingerprint=hashlib.sha256(active.current_account.wxid.encode()).hexdigest()[:12],
                         account_pinned=bool(config.expected_account_id))
            if not active.ready:
                raise ProbeError("source_not_ready")
            if not config.expected_account_id:
                return CapabilityReport(component="source", status="pending", facts=facts, gaps=["source_account_not_pinned"])
            if active.current_account.wxid != config.expected_account_id:
                raise ProbeError("source_account_mismatch")
            if active.cli_version.split()[0] != "0.7.4":
                return CapabilityReport(component="source", status="pending", facts=facts, gaps=["source_version_unverified"])
            gaps = await _samples(client, active, facts) if samples else []
            return CapabilityReport(component="source", status="pending" if gaps else "passed", facts=facts, gaps=gaps)
    except ProbeError as error:
        gap = str(error)
    except httpx.TimeoutException:
        gap = "source_timeout"
    except httpx.RequestError:
        gap = "source_unreachable"
    except ValidationError as error:
        facts["schema_errors"] = _schema_errors(error)
        gap = "source_contract_invalid"
    except (ValueError, TypeError, OverflowError):
        gap = "source_contract_invalid"
    return CapabilityReport(component="source", status="failed", facts=facts, gaps=[gap])
