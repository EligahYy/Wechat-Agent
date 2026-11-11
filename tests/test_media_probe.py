"""Local media checks are read-only and never imply successful parsing."""

import json
from pathlib import Path
import socket

import pytest


def test_missing_media_is_not_parsed(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    report = inspect_media(tmp_path / "absent.png")
    assert report["state"] == "missing"
    assert report["parsed"] is False


def test_empty_file_and_directory_do_not_count_as_available(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    empty = tmp_path / "empty.pdf"
    empty.touch()
    assert inspect_media(empty)["state"] == "failed"
    assert inspect_media(tmp_path)["state"] == "failed"


def test_hash_is_streamed_without_modifying_file(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    path = tmp_path / "sample.bin"
    path.write_bytes(b"abc")
    report = inspect_media(path)
    assert report["state"] == "available"
    assert report["size_bytes"] == 3
    assert report["sha256"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert report["parsed"] is False
    assert path.read_bytes() == b"abc"


def test_existing_file_does_not_imply_original_quality(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    path = tmp_path / "original-name.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    assert inspect_media(path)["quality"] == "unknown"
    assert inspect_media(path, quality="thumbnail")["quality"] == "thumbnail"
    assert inspect_media(path)["mime"] == "image/png"


def test_permission_failure_returns_specific_gap(tmp_path, monkeypatch):
    from wechat_agent.attachments.probe import inspect_media
    path = tmp_path / "no-access.bin"
    path.write_bytes(b"data")
    original = Path.open
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("must not echo private path")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    report = inspect_media(path)
    assert report["state"] == "failed"
    assert report["gap"] == "media_permission_denied"
    assert "must not echo" not in json.dumps(report)


def test_executable_media_is_never_executed(tmp_path):
    from wechat_agent.attachments.probe import inspect_media
    marker = tmp_path / "must-not-exist"
    path = tmp_path / "file.sh"
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    path.chmod(0o755)
    result = inspect_media(path)
    assert result["parsed"] is False
    assert not marker.exists()


def test_shareable_report_excludes_private_fields_and_preserves_useful_counts():
    from wechat_agent.evidence import sanitize_evidence
    private = {
        "schema_version": 1, "checked_at": "2026-11-11T09:19:07+00:00",
        "runtime": {"status": "passed", "facts": {"python": "3.12.13", "platform": "Darwin",
            "data_dir": "/Users/private-person/Library/Application Support/Wechat-Agent"}},
        "source": {"status": "passed", "facts": {"messages_checked": 6, "current_account": {"wxid": "wxid_private"},
            "raw": {"body": "private-chat"}, "api_key": "private-key"}},
        "model": {"status": "passed", "facts": {"usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3,
            "api_key": "private-key"}}},
        "media": {"status": "passed", "facts": {"files": [{"path": "/Users/private-person/price.xlsx", "name": "private-name.xlsx",
            "size_bytes": 3, "quality": "unknown", "parsed": False}]}},
    }
    result = sanitize_evidence(private)
    text = json.dumps(result)
    for secret in ("private-person", "wxid_private", "private-chat", "private-key", "private-name"):
        assert secret not in text
    assert result["source"]["facts"]["messages_checked"] == 6
    assert result["model"]["facts"]["usage"]["total_tokens"] == 3
    assert result["media"]["facts"]["files"][0]["size_bytes"] == 3
    assert private["source"]["facts"]["api_key"] == "private-key"


def test_shareable_message_issues_validate_metadata_and_drop_private_values():
    from wechat_agent.evidence import sanitize_evidence
    private = {"source": {"facts": {"message_issues": [{
        "reason": "message_sender_missing", "conversation_kind": "group",
        "item_index": 0, "page_offset": 2, "msg_type": 10000, "sub_type": 0,
        "direction": "incoming", "sender": "private-id", "content": "private-chat",
    }, {
        "reason": "private-reason", "conversation_kind": "private-name",
        "item_index": "private-index", "page_offset": True,
        "msg_type": "private-type", "sub_type": -1, "direction": "private-direction",
    }]}}}
    issues = sanitize_evidence(private)["source"]["facts"]["message_issues"]
    assert issues[0] == {
        "reason": "message_sender_missing", "conversation_kind": "group",
        "item_index": 0, "page_offset": 2, "msg_type": 10000, "sub_type": 0, "direction": "incoming",
    }
    assert "private-" not in json.dumps(issues)


def test_media_cli_is_offline_and_can_write_shareable_report(tmp_path, monkeypatch, capsys):
    from wechat_agent.doctor import main
    def forbidden(*args, **kwargs):
        raise AssertionError("Media-only diagnostics must remain offline")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    path = tmp_path / "private-filename.pdf"
    path.write_bytes(b"%PDF-1.4\nsynthetic only")
    report = tmp_path / "m0.json"
    public = tmp_path / "shareable.json"
    assert main(["--check-media", str(path), "--output", str(report), "--shareable-output", str(public)]) == 0
    private = json.loads(report.read_text())
    assert private["media"]["status"] == "passed"
    assert private["media"]["facts"]["parsed"] is False
    assert private["model"]["status"] == "pending"
    assert "private-filename" not in public.read_text()
    assert "private-filename" not in capsys.readouterr().out


def test_report_cannot_overwrite_source_config(tmp_path, capsys):
    from wechat_agent.doctor import main
    path = tmp_path / "source.json"
    original = '{"base_url":"http://127.0.0.1:9100"}'
    path.write_text(original)
    with pytest.raises(SystemExit) as exit_info:
        main(["--source-config", str(path), "--output", str(path)])
    assert exit_info.value.code == 2
    assert "report_output_conflicts_with_input" in capsys.readouterr().err
    assert path.read_text() == original


def test_report_cannot_overwrite_media_input(tmp_path, capsys):
    from wechat_agent.doctor import main
    path = tmp_path / "input.pdf"
    path.write_bytes(b"%PDF-content")
    with pytest.raises(SystemExit):
        main(["--check-media", str(path), "--output", str(path)])
    assert "report_output_conflicts_with_input" in capsys.readouterr().err
    assert path.read_bytes() == b"%PDF-content"
