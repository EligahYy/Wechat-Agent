"""Synthetic source builders and a reusable, account-scoped archive seed."""

from datetime import datetime
import json
from pathlib import Path


def make_message(**updates):
    from wechat_agent.source.contracts import MessageRecord
    data = dict(account_id="acct-1", conversation_id="group-1", message_id="fixture:group-1:1",
                sender_id="merchant-a", sent_at=datetime.fromisoformat("2026-11-11T18:00:00+08:00"),
                kind="text", body="Synthetic message", source_revision="source-v1",
                raw={"talker": "group-1", "content": {"Text": "Synthetic message"}})
    data.update(updates)
    return MessageRecord.model_validate(data)


def make_page(records=None, **updates):
    from wechat_agent.source.contracts import SourcePage
    data = dict(account_id="acct-1", conversation_id="group-1", conversation_kind="group",
                records=[make_message()] if records is None else records, next_cursor=None, complete=True)
    data.update(updates)
    return SourcePage.model_validate(data)


def seed_case(conn, name="source-overlap"):
    from wechat_agent.source.contracts import ContactRecord, ConversationRecord, SourcePage
    from wechat_agent.source.repository import archive_metadata, archive_page
    data = json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())
    contacts = [ContactRecord.model_validate(row) for row in data["contacts"]]
    conversations = [ConversationRecord.model_validate(row) for row in data["conversations"]]
    archive_metadata(conn, data["account_id"], contacts, conversations)
    with conn:
        for row in data["contacts"]:
            conn.execute("UPDATE contacts SET role=? WHERE account_id=? AND contact_id=?",
                         (row["role"], row["key"]["account_id"], row["key"]["contact_id"]))
    for page in data["pages"]:
        archive_page(conn, SourcePage.model_validate(page))
