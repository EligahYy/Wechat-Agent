"""Long customer analysis finishes beyond the old 12-request checkpoint."""

import sqlite3

from test_workspace_queue import model
from test_workspace_queue import ready as ready

from wechat_agent.db import DB, now
from wechat_agent.ingestion import ingest
from wechat_agent.workspace import agent, queue
from wechat_agent.workspace.context import build
from wechat_agent.workspace.packets import groups, progress
from wechat_agent.workspace.store import read
from wechat_agent.workspace.transport import ModelSession


def test_one_resume_finishes_823_messages_after_legacy_merge_checkpoint(
    ready, record, monkeypatch
):
    ingest(
        ready,
        [
            record
            | {
                "source_id": f"history-{n}",
                "sender_id": "merchant",
                "text": f"第{n}条历史沟通，保留原始线索",
            }
            for n in range(822)
        ],
    )
    context = build(ready, "merchant")
    pages = len(list(groups(context["payload"]["messages"])))
    trace = []

    def observe(payload):
        scan = ready.rows("SELECT * FROM workspace_scans")[0]
        trace.append(
            (
                payload.get("phase"),
                "draft" in payload,
                scan["phase"],
                scan["stage_completed"],
                scan["stage_total"],
                scan["merge_level"],
            )
        )

    with model(ready, observe) as client:
        # Reproduce an existing 26+-packet archive paused in merge, not extraction.
        with monkeypatch.context() as old:
            old.setattr(
                agent,
                "ModelSession",
                lambda *args: ModelSession(*args, limit=pages + 2),
            )
            paused = agent.run(ready, "merchant", client)
        assert paused["reason"] == "call_limit"
        checkpoint = ready.rows("SELECT * FROM workspace_scans")[0]
        assert checkpoint["phase"] == "merge"
        assert checkpoint["completed_pages"] == checkpoint["total_pages"] == pages
        assert checkpoint["processed_messages"] == 823
        extracted = sum(p[0] == "extract" for p in trace)
        requests = len(trace)
        result = queue.command(
            ready, "merchant", "resume", background=False, client=client
        )
    assert result["execution"] == "completed"
    assert len(trace) - requests > 12
    assert sum(p[0] == "extract" for p in trace) == extracted == pages
    assert any(p[2] == "merge" and p[3] > 0 and p[4] > p[3] for p in trace)
    assert any(p[2] == "summarize" and not p[1] for p in trace)
    assert any(p[2] == "review" and p[1] for p in trace)
    document = read(ready, "merchant")
    assert document["body"]["coverage"]["processed_messages"] == 823
    scan = ready.rows("SELECT * FROM workspace_scans")[0]
    assert scan["phase"] == "done" and scan["status"] == "succeeded"
    assert scan["stage_completed"] == scan["stage_total"] == 1
    assert queue.progress(ready)["items"] == []
    assert queue.report(ready)["counts"] == {"succeeded": 1}
    assert len(ready.rows("SELECT * FROM messages")) == 823


def test_stage_progress_is_not_whole_task_completion(ready):
    queue.reconcile(ready)
    progress(
        ready,
        "merchant",
        "fingerprint",
        26,
        26,
        823,
        823,
        phase="merge",
        stage_completed=2,
        stage_total=37,
        merge_level=1,
    )
    item = queue.progress(ready, background=False)["items"][0]
    assert item["phase_label"] == "合并资料"
    assert item["stage_detail"] == "第1轮合并：2 / 37 组"
    assert item["status"] != "succeeded"
    assert item["primary_action"]["action"] == "resume"
    assert item["completed_pages"] == item["total_pages"] == 26


def test_v15_upgrade_preserves_packets_and_manual_pause(ready):
    queue.reconcile(ready)
    progress(
        ready,
        "merchant",
        "fingerprint",
        26,
        26,
        823,
        823,
        phase="merge",
        status="paused",
        error="call_limit",
    )
    with ready.tx() as c:
        c.execute("UPDATE workspace_queue SET status='paused',error='call_limit'")
        c.execute(
            "INSERT INTO workspace_queue(account_id,source_id,input_revision,status,priority,error,available_at,updated_at,user_paused) VALUES('account','manual','old','paused',0,'call_limit',?,?,1)",
            (now(), now()),
        )
        for name in ("stage_completed", "stage_total", "merge_level"):
            c.execute("ALTER TABLE workspace_scans DROP COLUMN " + name)
        c.execute("PRAGMA user_version=14")
    DB(ready.settings)
    backup = sorted(ready.settings.data_dir.glob("pre-v15-*.sqlite3"))[-1]
    with sqlite3.connect(backup) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 14
        assert (
            c.execute("SELECT processed_messages FROM workspace_scans").fetchone()[0]
            == 823
        )
    scan = ready.rows("SELECT * FROM workspace_scans")[0]
    assert scan["processed_messages"] == 823 and scan["phase"] == "merge"
    assert scan["status"] == "queued" and scan["error"] is None
    assert scan["stage_completed"] == scan["stage_total"] == scan["merge_level"] == 0
    manual = ready.rows("SELECT * FROM workspace_queue WHERE source_id='manual'")[0]
    assert manual["user_paused"] == 1 and manual["status"] == "paused"
    assert ready.rows("PRAGMA user_version")[0]["user_version"] == 16
    assert len(ready.rows("SELECT * FROM messages")) == 1


def test_new_input_after_publication_is_labeled_as_update(ready, record):
    with model(ready) as client:
        assert (
            queue.command(ready, "merchant", "start", background=False, client=client)[
                "execution"
            ]
            == "completed"
        )
    assert queue.progress(ready)["items"] == []
    ingest(
        ready,
        [
            record
            | {
                "source_id": "new-input",
                "sender_id": "merchant",
                "text": "新一批货，明天补充资料",
            }
        ],
    )
    queue.reconcile(ready)
    item = queue.progress(ready, background=False)["items"][0]
    assert item["phase"] == "update" and item["phase_label"] == "新进展待整理"
    assert "上轮档案已保存" in item["stage_detail"]
    assert item["stage_total"] == 0
