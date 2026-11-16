"""The small-range Mac check stores originals locally and reports only counts."""

import json

import pytest


def test_cli_sample_replay_is_idempotent_and_does_not_print_personal_data(tmp_path, monkeypatch, capsys):
    from tests.fakes.source import FakeSource
    from wechat_agent.source import sync
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path / "private-data"))
    monkeypatch.setattr(sync, "WXCLIAdapter", lambda config: FakeSource())
    output = tmp_path / "shareable-sync.json"
    args = ["--source-account", "acct-1", "--sample", "--from-start", "--output", str(output)]
    assert sync.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["counts"]["inserted"] == 4
    assert first["counts"]["completed_conversations"] == 2
    assert first["history_complete"] is False
    assert sync.main(args) == 0
    second_text = capsys.readouterr().out
    second = json.loads(second_text)
    assert second["counts"]["inserted"] == second["counts"]["revised"] == 0
    assert second["counts"]["unchanged"] == 4
    assert json.loads(output.read_text()) == second
    for private in ("商家甲", "provider-p", "acct-1", "group-1", "private-data", "新批约12方"):
        assert private not in second_text


def test_cli_refuses_output_overwriting_source_config(tmp_path, monkeypatch):
    from wechat_agent.source import sync
    path = tmp_path / "source.json"
    original = '{"expected_account_id":"acct-1"}'
    path.write_text(original)
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(SystemExit) as error:
        sync.main(["--source-account", "acct-1", "--source-config", str(path), "--sample", "--output", str(path)])
    assert error.value.code == 2
    assert path.read_text() == original
    assert not (tmp_path / "data").exists()


def test_cli_sample_does_not_allow_unbounded_read_sizes(tmp_path, monkeypatch):
    from wechat_agent.source import sync
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as error:
        sync.main(["--source-account", "acct-1", "--sample", "--page-size", "500"])
    assert error.value.code == 2


def test_cli_attribution_gap_reports_safe_types_and_keeps_private_raw_in_database(tmp_path, monkeypatch, capsys):
    from tests.fakes.source import FakeSource
    from tests.factories import make_page
    from wechat_agent.source import sync
    from wechat_agent.source.contracts import SourceIssue
    issue = SourceIssue(code="message_sender_missing", message_id="fixture:group-1:bad",
                        raw={"talker": "group-1", "msg_type": 1, "sub_type": 0, "content": "private-chat"})
    source = FakeSource({"group-1": [make_page([], complete=False, issues=[issue], gaps=[issue.code])]})
    monkeypatch.setenv("WECHAT_AGENT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sync, "WXCLIAdapter", lambda config: source)
    assert sync.main(["--source-account", "acct-1", "--conversation", "group-1"]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["counts"]["unresolved_issues_total"] == 1
    assert report["issue_types"] == [{"code": "message_sender_missing", "msg_type": 1, "sub_type": 0,
                                      "conversation_kind": "group", "count": 1}]
    assert "private-chat" not in output
    assert "group-1" not in output


def test_cli_known_scope_warning_is_not_a_failed_read(tmp_path,monkeypatch,capsys):
    from wechat_agent.source import sync
    async def replay(*args):
        return sync.SyncResult(successful_conversations=['group-1'],gaps=['source_group_membership_unverified']),0,[],False
    monkeypatch.setenv('WECHAT_AGENT_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(sync,'_run_cli',replay)
    assert sync.main(['--source-account','acct-1','--conversation','group-1'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='passed' and report['history_complete'] is False
    assert report['warnings']==['source_group_membership_unverified']
