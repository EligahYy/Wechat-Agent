"""Review retained inferences without turning model guesses into raw evidence."""

import json

import pytest
from test_workspace import pilot as _pilot
from test_workspace import proposal

from wechat_agent.db import dumps, now
from wechat_agent.ingestion import ingest
from wechat_agent.services import Conflict
from wechat_agent.workspace.clues import key
from wechat_agent.workspace.context import build, snapshot
from wechat_agent.workspace.store import command, commit, raw, reference, stable
from wechat_agent.workspace.views import details, packets, sources

pilot = _pilot


def publish(db):
    context, result = proposal(db)
    anchor = result.evidence[0]
    context["unattributed"] = [
        {
            "section": "actions",
            "code": "workspace_customer_anchor_required",
            "item": {"text": "SELF已对接卡航，客户计划需要核实", "evidence": [anchor]},
        }
    ]
    return commit(db, "merchant", result, context, snapshot(db, "merchant"))


def test_verify_retained_clue_is_a_locked_note_not_a_task(pilot):
    doc = publish(pilot)
    item = details(pilot, "merchant")["body"]["unattributed"][0]
    assert "SELF" not in item["text"]
    verified = command(
        pilot,
        "merchant",
        doc["version"],
        "resolve_clue",
        item["id"],
        {
            "choice": "confirmed",
            "text": "客户需要我方确认英国报价",
            "belongs_to_customer": True,
        },
    )
    assert verified["body"]["actions"] == doc["body"]["actions"]
    assert verified["body"]["batches"] == doc["body"]["batches"]
    assert (
        not verified["body"]["unattributed"] and not verified["body"]["quality_issues"]
    )
    note = next(
        n for n in verified["body"]["notes"].values() if n.get("manual_verified")
    )
    assert note["text_locked"] and note["evidence"] == item["evidence"]
    assert note["text"] == "客户需要我方确认英国报价"
    assert not pilot.rows("SELECT * FROM usage")
    again = publish(pilot)
    assert not again["body"]["unattributed"]
    assert any(n.get("manual_verified") for n in again["body"]["notes"].values())
    memory = build(pilot, "merchant")["payload"]["document"]
    assert memory["clue_resolutions"][item["id"]]["choice"] == "confirmed"
    assert "original" not in memory["clue_resolutions"][item["id"]]
    note_id = next(
        ident for ident, n in again["body"]["notes"].items() if n.get("manual_verified")
    )
    corrected = command(
        pilot,
        "merchant",
        again["version"],
        "correct",
        "notes:" + note_id,
        "客户已更新为班列报价需求",
    )
    memory = build(pilot, "merchant")["payload"]["document"]
    assert memory["clue_resolutions"][item["id"]]["text"] == "客户已更新为班列报价需求"
    restored = command(
        pilot, "merchant", corrected["version"], "restore_clue", item["id"]
    )
    assert len(restored["body"]["unattributed"]) == 1
    assert not any(n.get("manual_verified") for n in restored["body"]["notes"].values())
    assert len(pilot.rows("SELECT * FROM workspace_versions")) == 5


def test_dismiss_and_restore_keep_original_and_do_not_reappear(pilot):
    doc = publish(pilot)
    item = doc["body"]["unattributed"][0]
    changed = command(
        pilot,
        "merchant",
        doc["version"],
        "resolve_clue",
        item["id"],
        {"choice": "dismissed"},
    )
    assert changed["body"]["notes"] == doc["body"]["notes"]
    assert (
        changed["body"]["clue_resolutions"][item["id"]]["original"]["text"]
        == item["text"]
    )
    again = publish(pilot)
    assert not again["body"]["unattributed"]
    assert (
        details(pilot, "merchant")["body"]["clue_resolutions"][item["id"]]["choice"]
        == "dismissed"
    )
    with pytest.raises(Conflict):
        command(
            pilot,
            "merchant",
            doc["version"],
            "resolve_clue",
            item["id"],
            {"choice": "dismissed"},
        )
    with pytest.raises(ValueError, match="workspace_clue_not_pending"):
        command(
            pilot,
            "merchant",
            again["version"],
            "resolve_clue",
            item["id"],
            {"choice": "dismissed"},
        )
    restored = command(pilot, "merchant", again["version"], "restore_clue", item["id"])
    assert restored["body"]["unattributed"][0]["text"] == item["text"]
    assert not restored["body"]["clue_resolutions"]


@pytest.mark.parametrize(
    "value",
    [
        {"choice": "confirmed", "text": "客户有报价需求"},
        {"choice": "confirmed", "text": "  ", "belongs_to_customer": True},
        {
            "choice": "confirmed",
            "text": "客户有报价需求",
            "belongs_to_customer": "true",
        },
        {"choice": "unknown"},
    ],
)
def test_invalid_review_does_not_write(pilot, value):
    doc = publish(pilot)
    with pytest.raises(ValueError):
        command(
            pilot,
            "merchant",
            doc["version"],
            "resolve_clue",
            doc["body"]["unattributed"][0]["id"],
            value,
        )
    assert raw(pilot, "merchant")["version"] == doc["version"]
    assert len(pilot.rows("SELECT * FROM workspace_versions")) == 1


def test_review_is_revision_and_exclusion_scoped(pilot, record):
    doc = publish(pilot)
    item = doc["body"]["unattributed"][0]
    command(
        pilot,
        "merchant",
        doc["version"],
        "resolve_clue",
        item["id"],
        {"choice": "dismissed"},
    )
    ingest(pilot, [record | {"sender_id": "merchant", "text": "更新后的英国报价需求"}])
    with pytest.raises(ValueError, match="workspace_stale_evidence"):
        command(pilot, "merchant", 2, "restore_clue", item["id"])
    current = publish(pilot)
    fresh = details(pilot, "merchant")
    assert fresh["body"]["unattributed"][0]["id"] != item["id"]
    assert not fresh["body"]["clue_resolutions"]
    assert current["body"][
        "clue_resolutions"
    ]  # Retained in local audit, not used as fresh evidence.
    with pilot.tx() as c:
        c.execute("INSERT INTO actor_exclusions VALUES('account','merchant','同事')")
    with pytest.raises(ValueError, match="workspace_excluded_person"):
        command(
            pilot,
            "merchant",
            current["version"],
            "resolve_clue",
            fresh["body"]["unattributed"][0]["id"],
            {"choice": "dismissed"},
        )


def test_legacy_clue_ids_are_stable_and_alias_presentation_does_not_change_them(pilot):
    doc = publish(pilot)
    item = doc["body"]["unattributed"][0]
    with pilot.tx() as c:
        body = doc["body"]
        body["unattributed"][0].pop("id")
        c.execute("UPDATE workspace_documents SET body=?", (dumps(body),))
    shown = details(pilot, "merchant")["body"]["unattributed"][0]
    assert shown["id"] == key(item) == key(shown)
    changed = command(
        pilot,
        "merchant",
        doc["version"],
        "resolve_clue",
        shown["id"],
        {"choice": "dismissed"},
    )
    assert not changed["body"]["unattributed"]


def test_packet_self_labels_use_source_direction_and_preserve_raw_records(
    pilot, record
):
    ingest(
        pilot,
        [
            record
            | {
                "source_id": "self-message",
                "sender_id": "account",
                "direction": "outgoing",
                "text": "SELF是原始文件中的标记，卡航10.8元/kg",
            }
        ],
    )
    ctx = build(pilot, "merchant")
    ref, m = next(
        (k, v) for k, v in ctx["evidence"].items() if v["direction"] == "outgoing"
    )
    stored = {
        "facts": [
            {
                "kind": "quote",
                "subject": "other",
                "text": "SELF提到卡航10.8元/kg",
                "evidence": [ref],
            }
        ]
    }
    with pilot.tx() as c:
        c.execute(
            "INSERT INTO workspace_packets VALUES(?,?,?,?,?,?,?)",
            (
                stable("synthetic-packet"),
                "account",
                "merchant",
                "extract",
                dumps([reference(m)]),
                dumps(stored),
                now(),
            ),
        )
    shown = packets(pilot, "merchant")["items"][0]["body"]["facts"][0]
    assert shown["subject_label"] == "我方（工作微信）"
    assert shown["text"] == "我方提到卡航10.8元/kg"
    assert (
        json.loads(pilot.rows("SELECT body FROM workspace_packets")[0]["body"])
        == stored
    )
    assert any(
        m["text"].startswith("SELF") for m in sources(pilot, "merchant")["items"]
    )
    assert not pilot.rows("SELECT * FROM usage")


def test_unrelated_source_edit_preserves_valid_human_review(pilot, record):
    background = record | {"source_id": "background", "text": "服务商普通背景"}
    ingest(pilot, [background])
    doc = publish(pilot)
    item = doc["body"]["unattributed"][0]
    command(
        pilot,
        "merchant",
        doc["version"],
        "resolve_clue",
        item["id"],
        {
            "choice": "confirmed",
            "text": "客户需要英国报价",
            "belongs_to_customer": True,
        },
    )
    ingest(pilot, [background | {"text": "修订后的服务商普通背景"}])
    memory = build(pilot, "merchant")["payload"]["document"]
    assert any(n.get("manual_verified") for n in memory["notes"].values())
    assert memory["clue_resolutions"][item["id"]]["choice"] == "confirmed"
    updated = publish(pilot)
    assert any(n.get("manual_verified") for n in updated["body"]["notes"].values())
    assert not updated["body"]["unattributed"]
