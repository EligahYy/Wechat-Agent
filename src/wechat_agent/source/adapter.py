"""Pinned, read-only wx-cli adapter. No shell commands, proxies or media parsing."""

import hashlib
import json
import os
import time
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from .contracts import (AttachmentFetch, CapabilityReport, ContactKey, ContactRecord,
                        ConversationRecord, SourceIssue, SourcePage)
from .probe import ProbeError, SourceConfig, _get
from .wx_cli import Envelope, Health, parse_message, sender_issue_code
from ..identities import is_person_identifier


class SourceError(Exception):
    """A fixed technical code; never contains upstream bodies or credential values."""


class Cursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    account_id: str
    conversation_id: str
    offset: StrictInt = Field(ge=0)
    limit: StrictInt = Field(ge=1, le=500)
    until: StrictInt = Field(ge=0)
    last_key: tuple[StrictInt, StrictInt, StrictInt] | None = None


class WXCLIAdapter:
    def __init__(self, config: SourceConfig, *, transport=None):
        if not config.expected_account_id or not config.expected_account_id.strip():
            raise SourceError("source_account_not_pinned")
        self._account_id = config.expected_account_id
        token = os.getenv(config.token_env) if config.token_env else None
        if config.token_env and not token:
            raise SourceError("source_token_not_configured")
        self._client = httpx.AsyncClient(base_url=config.base_url, trust_env=False, follow_redirects=False,
                                         timeout=config.timeout_seconds, transport=transport,
                                         headers={"Authorization": f"Bearer {token}"} if token else {})
        self._worker = None
        self._people = None
        self._groups = {}
        self._self_name = None

    @property
    def account_id(self):
        return self._account_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _read(self, path, params=None):
        try:
            return await _get(self._client, path, params)
        except ProbeError as error:
            raise SourceError(str(error)) from None
        except httpx.TimeoutException:
            raise SourceError("source_timeout") from None
        except httpx.RequestError:
            raise SourceError("source_unreachable") from None

    async def _health(self):
        try:
            active = Health.model_validate(await self._read("/api/v1/health"))
        except ValidationError:
            raise SourceError("source_contract_invalid") from None
        if active.current_account.wxid != self.account_id:
            raise SourceError("source_account_mismatch")
        if not active.ready:
            raise SourceError("source_not_ready")
        if active.cli_version.split()[0] != "0.7.4":
            raise SourceError("source_version_unverified")
        if self._worker is not None and self._worker != active.worker_id:
            raise SourceError("source_changed_during_sync")
        self._worker = active.worker_id
        self._self_name = active.current_account.name or None
        return active

    async def check(self):
        try:
            active = await self._health()
        except SourceError as error:
            return CapabilityReport(component="source", status="failed", gaps=[str(error)])
        return CapabilityReport(component="source", status="passed", facts={
            "scope": "connection", "history_complete": False, "ready": True,
            "cli_version": active.cli_version,
            "account_fingerprint": hashlib.sha256(self.account_id.encode()).hexdigest()[:12]})

    async def _page(self, path, params):
        await self._health()
        raw = await self._read(path, params)
        await self._health()
        try:
            page = Envelope.model_validate(raw)
        except ValidationError:
            raise SourceError("source_contract_invalid") from None
        if (page.paging.offset != params["offset"] or page.paging.limit != params["limit"]
                or len(page.items) > params["limit"]):
            raise SourceError("source_pagination_mismatch")
        return page

    async def _metadata(self, path, identity):
        rows = []
        seen = set()
        for offset in range(0, 200000, 200):
            page = await self._page(path, {"limit": 200, "offset": offset, "show_hidden": "1", "order": "asc"})
            if page.stats.skipped or page.stats.shard_warnings:
                raise SourceError("source_metadata_partial")
            for row in page.items:
                identifier = row.get(identity)
                if not isinstance(identifier, str) or not identifier.strip():
                    raise SourceError("source_metadata_identity_missing")
                if identifier in seen:
                    raise SourceError("source_metadata_no_progress")
                seen.add(identifier)
                rows.append(row)
            if not page.paging.has_more:
                return rows
            if not page.items:
                raise SourceError("source_metadata_no_progress")
        raise SourceError("source_metadata_page_limit_reached")

    async def contacts(self):
        people = []
        groups = {}
        for row in await self._metadata("/api/v1/contacts", "user_name"):
            identifier = row["user_name"]
            if identifier.endswith("@chatroom"):
                groups[identifier] = row.get("remark") or row.get("nick_name") or None
                continue
            try:
                people.append(ContactRecord(key=ContactKey(account_id=self.account_id, contact_id=identifier),
                                            remark=row.get("remark") or None, nickname=row.get("nick_name") or None,
                                            is_self=identifier == self.account_id))
            except ValidationError:
                raise SourceError("source_contact_contract_invalid") from None
        if not any(person.is_self for person in people):
            people.append(ContactRecord(key=ContactKey(account_id=self.account_id, contact_id=self.account_id),
                                        remark=None, nickname=self._self_name, is_self=True))
        self._people, self._groups = people, groups
        return people

    async def conversations(self):
        if self._people is None:
            await self.contacts()
        rooms = {}
        for row in await self._metadata("/api/v1/sessions", "username"):
            identifier = row["username"]
            kind = "group" if identifier.endswith("@chatroom") else "private"
            try:
                rooms[identifier] = ConversationRecord(
                    account_id=self.account_id, conversation_id=identifier, kind=kind,
                    title=row.get("display_name") or None,
                    member_ids=[] if kind == "group" else list({identifier, self.account_id}))
            except ValidationError:
                raise SourceError("source_conversation_contract_invalid") from None
        for identifier, title in self._groups.items():
            rooms.setdefault(identifier, ConversationRecord(account_id=self.account_id, conversation_id=identifier,
                                                            kind="group", title=title))
        for person in self._people:
            if not person.is_self and is_person_identifier(person.key.contact_id):
                identifier = person.key.contact_id
                rooms.setdefault(identifier, ConversationRecord(
                    account_id=self.account_id, conversation_id=identifier, kind="private",
                    title=person.remark or person.nickname, member_ids=[identifier, self.account_id]))
        return list(rooms.values())

    async def messages(self, conversation_id, cursor, limit):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise SourceError("source_page_size_invalid")
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise SourceError("source_conversation_identity_missing")
        if cursor is None:
            position = Cursor(account_id=self.account_id, conversation_id=conversation_id,
                              offset=0, limit=limit, until=int(time.time()))
        else:
            try:
                if len(cursor) > 8192:
                    raise ValueError
                position = Cursor.model_validate_json(cursor)
            except (ValidationError, ValueError, TypeError):
                raise SourceError("source_cursor_invalid") from None
            if position.account_id != self.account_id or position.conversation_id != conversation_id:
                raise SourceError("source_cursor_scope_mismatch")
            if position.limit != limit:
                raise SourceError("source_cursor_page_size_mismatch")
        page = await self._page("/api/v1/messages", {
            "contact": conversation_id, "offset": position.offset, "limit": limit,
            "until": position.until, "order": "asc", "show_hidden": "1"})
        if any(row.get("talker") != conversation_id for row in page.items):
            raise SourceError("source_message_scope_mismatch")
        gaps, issues, records = [], [], []
        if page.stats.skipped:
            gaps.append("source_rows_skipped")
        if page.stats.shard_warnings:
            gaps.append("source_shards_unavailable")
        previous = position.last_key
        for row in page.items:
            try:
                record = parse_message(row, self.account_id)
            except ValidationError as error:
                code = sender_issue_code(error)
            except (ValueError, OverflowError, OSError) as error:
                code = "source_message_id_unavailable" if str(error) == "message_id_unavailable" else "message_contract_invalid"
            else:
                key = tuple(row[field] for field in ("sort_seq", "create_time", "server_id"))
                if previous is not None and key <= previous:
                    raise SourceError("source_page_no_progress")
                previous = key
                records.append(record)
                continue
            server_id = row.get("server_id")
            identifier = (f"wx-cli:{quote(conversation_id, safe='')}:{server_id}"
                          if type(server_id) is int and server_id > 0 else None)
            issues.append(SourceIssue(code=code, message_id=identifier, raw=row))
            gaps.append(code)
        if not page.items and page.paging.has_more:
            gaps.append("source_empty_page_with_more")
        if gaps:
            next_cursor = cursor
        elif page.paging.has_more:
            next_cursor = position.model_copy(update={"offset": position.offset + limit, "last_key": previous}).model_dump_json()
        else:
            next_cursor = None
        return SourcePage(account_id=self.account_id, conversation_id=conversation_id,
                          conversation_kind="group" if conversation_id.endswith("@chatroom") else "private",
                          records=records, next_cursor=next_cursor, complete=not gaps and not page.paging.has_more,
                          gaps=sorted(set(gaps)), issues=issues)

    async def fetch_attachment(self, attachment_id):
        return AttachmentFetch(attachment_id=attachment_id, state="unavailable", content=None, mime=None,
                               reason="media_fetch_not_implemented_in_m1")
