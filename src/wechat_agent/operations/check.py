"""Bounded API/worker validation; output contains technical state only."""

import argparse
import json
from pathlib import Path
import time
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from ..config import Settings
from ..source.probe import SourceConfig
from .service import initial_counts


def check_operation(client, account_id, *, wait_seconds=30, operation_id=None, latest=False):
    if latest:
        if operation_id is not None:
            raise ValueError("conflicting_operation_selection")
        response = client.get("/api/operations", params={"account_id": account_id, "page": 1, "page_size": 1})
        response.raise_for_status()
        items = response.json()["items"]
        if not items:
            raise ValueError("operation_not_found")
        operation_id = items[0]["id"]
    if operation_id is None:
        response = client.post("/api/operations", json={
            "action": "sync", "scope": {"account_id": account_id},
            "idempotency_key": str(uuid4()),
            "options": {"sample": True, "from_start": True},
        })
        response.raise_for_status()
        operation_id = str(UUID(response.json()["id"]))
    else:
        operation_id = str(UUID(operation_id))
    deadline = time.monotonic() + wait_seconds
    while True:
        response = client.get(f"/api/operations/{operation_id}", params={"account_id": account_id})
        response.raise_for_status()
        operation = response.json()
        if operation["state"] in {"succeeded", "failed", "stopped"} or time.monotonic() >= deadline:
            break
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    report = {
        "schema_version": 1,
        "operation_id": operation_id,
        "state": operation["state"],
        "source_state": operation["source_state"],
        "phase": operation["phase"],
        "error_code": operation["error_code"],
        "history_complete": False,
        "counts": {key: operation["counts"].get(key, 0) for key in initial_counts()},
        "source_gaps": [gap for item in operation["items"] if item["phase"] == "source" for gap in item["gaps"]],
    }
    for key in ('contacts_total', 'contacts_current', 'contacts_retained'):
        value = operation['counts'].get(key)
        if type(value) is int and value >= 0:
            report['counts'][key] = value
    try:
        response = client.get("/api/contacts", params={"account_id": account_id, "page_size": 1})
        response.raise_for_status()
        quality = response.json().get("identity_quality", {})
        report["contact_quality"] = {
            key: value for key in ("quarantined", "names_unavailable")
            if type(value := quality.get(key)) is int and value >= 0
        }
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        pass  # Contact diagnostics must not hide a saved source failure.
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8766")
    parser.add_argument("--wait", type=float, default=30)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--operation-id", help="Read an existing operation without creating another.")
    selection.add_argument("--latest", action="store_true", help="Read the latest saved operation; do not start a sync.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not 0 <= args.wait <= 300:
        parser.error("invalid_wait_limit")
    try:
        base_url = SourceConfig(base_url=args.url).base_url
        if args.operation_id:
            UUID(args.operation_id)
    except (ValidationError, ValueError):
        parser.error("invalid_local_api_or_operation_id")
    settings = Settings.load()
    protected = [settings.data_dir / name for name in ("archive.sqlite3", "archive.sqlite3-wal", "archive.sqlite3-shm")]
    protected += [Path.cwd() / ".local/config" / name for name in ("source.json", "model.json")]
    protected += [path for path in (settings.source_config, settings.model_config) if path]
    if args.output and args.output.expanduser().resolve() in {path.resolve() for path in protected}:
        parser.error("report_output_conflicts_with_input")
    try:
        with httpx.Client(base_url=base_url, trust_env=False, follow_redirects=False, timeout=5) as client:
            report = check_operation(client, args.account, wait_seconds=args.wait, operation_id=args.operation_id, latest=args.latest)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        report = {"schema_version": 1, "state": "failed", "error_code": "operation_check_failed"}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        path = args.output.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if report["state"] in {"failed", "stopped"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
