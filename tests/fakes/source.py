"""A deterministic source that preserves all speakers and records read cursors."""

import asyncio
import json
from pathlib import Path

from wechat_agent.source.contracts import CapabilityReport, ContactRecord, ConversationRecord, SourcePage


class FakeSource:
    def __init__(self, pages=None):
        data = json.loads((Path(__file__).parents[1] / "fixtures/source-overlap.json").read_text())
        self.account_id = data["account_id"]
        self.people = [ContactRecord.model_validate(row) for row in data["contacts"]]
        self.rooms = [ConversationRecord.model_validate(row) for row in data["conversations"]]
        self.pages = pages or {row["conversation_id"]: [SourcePage.model_validate(row)] for row in data["pages"]}
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def check(self):
        return CapabilityReport(component="source", status="passed", facts={"history_complete": False})

    async def contacts(self):
        return self.people

    async def conversations(self):
        return self.rooms

    async def messages(self, conversation_id, cursor, limit):
        self.calls.append((conversation_id, cursor, limit))
        await asyncio.sleep(0)
        index = int(cursor.split(":")[1]) if cursor else 0
        return self.pages[conversation_id][index]

    async def fetch_attachment(self, attachment_id):
        raise AssertionError("Message sync must not fetch media")
