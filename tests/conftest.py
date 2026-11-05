import pytest

from wechat_agent.config import Settings
from wechat_agent.db import DB
from wechat_agent.services import allow_conversation, create_merchant, create_project


@pytest.fixture
def db(tmp_path):
    return DB(Settings(data_dir=tmp_path))


@pytest.fixture
def chat(db):
    mid = create_merchant(db, "商家甲")
    pid = create_project(db, mid, "第一批", "美国")
    return allow_conversation(
        db,
        "fixture",
        "account",
        "chat",
        "三方群",
        "group",
        mid,
        pid,
        True,
        followup_source=True,
    )


@pytest.fixture
def record():
    return dict(
        source="fixture",
        account_id="account",
        conversation_id="chat",
        conversation_type="group",
        source_id="1",
        sender_id="provider",
        direction="incoming",
        event_time="2026-11-04T09:00:00+08:00",
        message_type="text",
        text="商家甲请提供体积，我是服务商，明天核实附加费。手机号13812345678",
    )
