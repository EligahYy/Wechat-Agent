"""One command service and one task projection for every analysis entry."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_workspace_queue import model
from test_workspace_queue import ready as ready

from wechat_agent.analysis import Blocked
from wechat_agent.workspace import queue
from wechat_agent.workspace.packets import progress as scan
from wechat_agent.workspace.store import read


def test_idle_and_queued_are_not_running_and_share_summary(ready):
    queue.reconcile(ready)
    data = queue.progress(ready)
    assert data["summary"]["counts"] == {"ready": 1}
    assert data["items"][0]["primary_action"] == {
        "action": "start",
        "label": "开始分析",
        "disabled": False,
    }
    queue.configure(ready, True)
    assert queue.progress(ready)["summary"]["counts"] == {"queued": 1}
    assert queue.progress(ready)["items"][0]["primary_action"]["action"] == "start"
    # Without a worker even an enabled automatic flag is not an executing job.
    assert queue.progress(ready, background=False)["summary"]["counts"] == {"ready": 1}
    counts = queue.report(ready, background=False)["counts"]
    assert counts == queue.progress(ready, background=False)["summary"]["counts"]
    result = queue.command(ready, "merchant", "pause", background=False)
    assert result["execution"] == "ready" and not result["paused"]
    assert not ready.rows("SELECT user_paused FROM workspace_queue")[0]["user_paused"]
    assert not ready.rows("SELECT * FROM usage")


def test_stale_running_records_do_not_offer_pause(ready):
    queue.reconcile(ready)
    scan(ready, "merchant", "old", 3, 1, 75, 32)
    with ready.tx() as c:
        c.execute(
            "UPDATE workspace_queue SET status='running',updated_at='2000-01-01T00:00:00+00:00'"
        )
    data = queue.progress(ready)
    assert data["summary"]["counts"] == {"ready": 1}
    assert data["items"][0]["primary_action"]["action"] == "resume"
    queue.configure(ready, True)
    with model(ready) as client:
        assert queue.step(ready, client=client)
    assert queue.progress(ready)["items"] == []


def test_live_manual_task_pause_resume_and_duplicate_commands(ready):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def hold(payload):
        calls.append(payload.get("phase"))
        if payload.get("phase") == "extract":
            entered.set()
            assert release.wait(10), "test request was not released"

    with ThreadPoolExecutor(max_workers=1) as pool, model(ready, hold) as client:
        future = pool.submit(
            queue.command, ready, "merchant", "start", background=False, client=client
        )
        try:
            assert entered.wait(5)
            data = queue.progress(ready, background=False)
            assert data["summary"]["counts"] == {"running": 1}
            assert data["items"][0]["primary_action"]["action"] == "pause"
            for action in ("start", "resume", "retry"):
                assert (
                    queue.command(ready, "merchant", action, background=False)[
                        "execution"
                    ]
                    == "running"
                )
            assert len(calls) == 1
            assert (
                queue.command(ready, "merchant", "pause", background=False)["execution"]
                == "stopping"
            )
            data = queue.progress(ready, background=False)
            assert data["summary"]["counts"] == {"stopping": 1}
            assert data["items"][0]["primary_action"] is None
            with pytest.raises(Blocked, match="workspace_pause_pending"):
                queue.command(ready, "merchant", "resume", background=False)
        finally:
            release.set()
        assert future.result(timeout=5)["execution"] == "paused"
    assert not read(ready, "merchant")
    assert queue.progress(ready)["items"][0]["primary_action"]["action"] == "resume"
    with model(ready) as client:
        result = queue.command(
            ready, "merchant", "resume", background=False, client=client
        )
    assert result["execution"] == "completed"
    assert queue.progress(ready)["items"] == []
    # Extraction already returned before stopping, so only synthesis/review remain.
    assert len(ready.rows("SELECT * FROM usage")) == 3


def test_worker_does_not_steal_live_manual_claim(ready):
    entered, release = threading.Event(), threading.Event()

    def hold(payload):
        if payload.get("phase") == "extract":
            entered.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool, model(ready, hold) as client:
        future = pool.submit(
            queue.command, ready, "merchant", "start", background=False, client=client
        )
        try:
            assert entered.wait(5)
            queue.configure(ready, True)
            with model(ready) as worker_client:
                assert not queue.step(ready, client=worker_client)
            assert (
                ready.rows("SELECT status FROM workspace_queue")[0]["status"]
                == "running"
            )
        finally:
            release.set()
        assert future.result(timeout=5)["execution"] == "completed"
    assert queue.report(ready)["counts"] == {"succeeded": 1}


@pytest.mark.parametrize(
    ("path", "action"),
    [
        ("jobs/command", "resume"),
        ("progress/control", "resume"),
        ("analyze", "start"),
        ("queue/retry", "retry"),
    ],
)
def test_all_http_entries_dispatch_one_command(ready, monkeypatch, path, action):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    calls = []

    def dispatch(db, source, selected, **kwargs):
        calls.append((source, selected, kwargs))
        return {"source_id": source, "execution": "completed"}

    monkeypatch.setattr(queue, "command", dispatch)
    client = TestClient(create_app(ready.settings))
    headers = {"Authorization": "Bearer " + ready.token}
    result = client.post(
        "/api/workspace/" + path,
        headers=headers,
        json={"source_id": "merchant", "action": "resume"},
    )
    assert result.status_code == 200
    assert calls == [("merchant", action, {"background": False})]


def test_progress_endpoint_counts_and_buttons_share_same_payload(ready):
    from fastapi.testclient import TestClient

    from wechat_agent.web import create_app

    queue.reconcile(ready)
    client = TestClient(create_app(ready.settings))
    headers = {"Authorization": "Bearer " + ready.token}
    data = client.get("/api/workspace/progress", headers=headers).json()
    assert data["summary"]["counts"] == {"ready": 1}
    assert data["items"][0]["primary_action"]["action"] == "start"
    assert (
        client.post(
            "/api/workspace/jobs/command",
            headers=headers,
            json={"source_id": "merchant", "action": []},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workspace/jobs/command",
            headers=headers,
            json={"source_id": "unknown", "action": "start"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/workspace/jobs/command",
            json={"source_id": "merchant", "action": "pause"},
        ).status_code
        == 401
    )


def test_cli_uses_same_command_service(ready, monkeypatch, capsys):
    from wechat_agent.cli import main

    calls = []

    def dispatch(db, source, action, **kwargs):
        calls.append((source, action, kwargs))
        return {"execution": "completed"}

    monkeypatch.setattr(queue, "command", dispatch)
    monkeypatch.setattr(
        "sys.argv",
        [
            "wechat-agent",
            "--data-dir",
            str(ready.settings.data_dir),
            "rebuild",
            "analyze",
            "--contact",
            "merchant",
        ],
    )
    main()
    assert calls == [("merchant", "start", {"background": False})]
    assert "completed" in capsys.readouterr().out
