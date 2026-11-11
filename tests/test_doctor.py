"""Diagnostics must never turn missing connections into successful checks."""

import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path


def test_missing_connections_stay_pending_on_mac(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    from wechat_agent.doctor import build_report

    report = build_report(data_dir=tmp_path, source=None, model=None)
    assert report["source"]["status"] == "pending"
    assert report["model"]["status"] == "pending"


def test_non_mac_source_is_explicitly_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    from wechat_agent.doctor import build_report

    report = build_report(data_dir=tmp_path, source=None, model=None)
    assert report["source"]["status"] == "unsupported"
    assert "mac_required" in report["source"]["gaps"]
    assert report["model"]["status"] == "pending"


def test_default_diagnostics_do_not_connect_or_create_data(tmp_path, monkeypatch):
    def forbidden_connection(*args, **kwargs):
        raise AssertionError("Default diagnostics must not use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connection)
    from wechat_agent.doctor import build_report

    data_dir = tmp_path / "not-created"
    report = build_report(data_dir=data_dir, source=None, model=None)
    assert report["runtime"]["status"] == "passed"
    assert not data_dir.exists()


def test_report_does_not_serialize_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    from wechat_agent.doctor import build_report

    report = build_report(
        data_dir=tmp_path,
        source={"status": "passed", "facts": {"version": "1", "api_key": "private-key"}},
        model={"status": "failed", "facts": {"nested": {"Authorization": "Bearer private-token"}}},
    )
    text = json.dumps(report)
    assert "private-key" not in text
    assert "private-token" not in text
    assert report["source"]["facts"]["version"] == "1"


def test_mac_settings_resolve_data_and_existing_probe_configs(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("WECHAT_AGENT_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / ".local" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "source.json").write_text("{}", encoding="utf-8")
    from wechat_agent.config import Settings

    settings = Settings.load()
    assert settings.data_dir == tmp_path / "home/Library/Application Support/Wechat-Agent"
    assert settings.source_config == config_dir / "source.json"
    assert settings.model_config is None


def test_explicit_data_directory_is_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path / "custom data"))
    from wechat_agent.config import Settings

    assert Settings.load().data_dir == tmp_path / "custom data"


def test_cli_writes_report_to_path_with_spaces_without_leaking_environment(tmp_path):
    output = tmp_path / "folder with spaces" / "report.json"
    result = subprocess.run(
        [sys.executable, "-m", "wechat_agent.doctor", "--output", str(output)],
        capture_output=True,
        text=True,
        env={**os.environ, "DEEPSEEK_API_KEY": "never-print-this-key"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["model"]["status"] == "pending"
    assert report["media"]["status"] == "pending"
    assert "never-print-this-key" not in output.read_text(encoding="utf-8")
    assert "never-print-this-key" not in result.stdout + result.stderr
