from datetime import UTC, datetime

import pytest

from wechat_agent.cli import parser
from wechat_agent.ingestion import ingest
from wechat_agent.rebuild import inspect_sources


def test_inventory_respects_user_scope_not_legacy_model_labels(db, chat, record):
    db.settings.bind_source("account")
    ingest(db, [record])
    with db.tx() as c:
        c.execute(
            "INSERT INTO conversation_classifications VALUES(?,?,?,?)",
            (chat, "provider", "[]", "2026-11-04"),
        )
    before = db.rows("SELECT * FROM messages")
    report = inspect_sources(db, at=datetime(2026, 11, 8, tzinfo=UTC))
    assert report["messages"]["recent_15_days"] == 1
    assert report["identities"]["non_exempt_missing_name"] == 1
    assert report["model_calls"] == 0
    assert "手机号" not in str(report)
    assert db.rows("SELECT * FROM messages") == before
    with db.tx() as c:
        c.execute("UPDATE conversations SET followup_source=0 WHERE id=?", (chat,))
    assert inspect_sources(db)["messages"]["eligible_full_text"] == 0


def test_person_exemption_only_blocks_own_private_not_shared_group(db, chat, record):
    db.settings.bind_source("account")
    ingest(db, [record])
    with db.tx() as c:
        c.execute(
            "INSERT INTO actor_exclusions VALUES('account','provider','coworker')"
        )
    assert inspect_sources(db)["messages"]["eligible_full_text"] == 1
    with db.tx() as c:
        c.execute(
            "UPDATE conversations SET kind='private',source_id='provider' WHERE id=?",
            (chat,),
        )
    r = inspect_sources(db)
    assert r["messages"]["archived"] == 1
    assert r["messages"]["eligible_full_text"] == 0
    assert r["identities"]["non_exempt_missing_name"] == 0


def test_inventory_requires_bound_account_and_excludes_other_accounts(db, chat, record):
    with pytest.raises(ValueError, match="绑定"):
        inspect_sources(db)
    ingest(db, [record])
    db.settings.bind_source("another-account")
    assert inspect_sources(db)["messages"]["archived"] == 0
    with pytest.raises(ValueError, match="时区"):
        inspect_sources(db, at=datetime(2026, 11, 8))
    assert parser().parse_args(["rebuild", "inspect"]).action == "inspect"
