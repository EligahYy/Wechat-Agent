import pytest
from pydantic import ValidationError
from test_crm import drain, model, response, setup_work_chat

from wechat_agent.analysis import CRM_PROMPT
from wechat_agent.crm import configure, schedule
from wechat_agent.crm_schema import PARTY_VALUES, Action


def action(party):
    return {
        "customer_ref": "C001",
        "action_key": "确认费用",
        "operation": "create",
        "summary": "核实费用",
        "reason": "商家询价",
        "party": party,
        "evidence_refs": ["E001"],
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ("other", "other"),
        ("platform", "self"),
        ("平台运营", "self"),
        ("客户", "merchant"),
        ("customer", "merchant"),
        ("服务商", "service_provider"),
        ("logistics_provider", "service_provider"),
        ("Service Provider", "service_provider"),
        ("未知", "unknown"),
        (None, "unknown"),
        ("", "unknown"),
        ("   ", "unknown"),
    ],
)
def test_only_unambiguous_party_labels_are_normalized(value, expected):
    assert Action.model_validate(action(value)).party == expected


@pytest.mark.parametrize(
    "value",
    ["C001", "张先生", "self_and_merchant", ["self", "merchant"], {"role": "self"}],
)
def test_id_name_and_multi_party_values_remain_invalid(value):
    with pytest.raises(ValidationError):
        Action.model_validate(action(value))


def test_prompt_uses_the_schema_party_enum_and_missing_party_is_unknown():
    assert list(PARTY_VALUES) == [
        "self",
        "merchant",
        "service_provider",
        "other",
        "unknown",
    ]
    assert '["self", "merchant", "service_provider", "other", "unknown"]' in CRM_PROMPT
    value = action("self")
    value.pop("party")
    assert Action.model_validate(value).party == "unknown"


def test_live_shaped_alias_response_builds_customer_and_task_without_schema_failure(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key")
    setup_work_chat(db, record)
    configure(db, True)
    result = response(db)
    result["actions"][0]["party"] = "物流服务商"
    drain(db, model(result))
    assert db.rows("SELECT party FROM crm_actions") == [{"party": "service_provider"}]
    assert len(db.rows("SELECT * FROM crm_customers")) == 1
    assert db.rows(
        "SELECT status FROM jobs WHERE json_extract(payload,'$.planner')=3"
    ) == [{"status": "succeeded"}]


def test_party_normalization_does_not_relax_evidence_validation(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key")
    setup_work_chat(db, record)
    configure(db, True)
    result = response(db, refs=["E999"])
    result["actions"][0]["party"] = "other"
    drain(db, model(result))
    assert not db.rows("SELECT * FROM crm_customers")
    assert not db.rows("SELECT * FROM crm_actions")


def test_manual_retry_resets_schema_failed_retry_wait_immediately(
    db, record, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-test-key")
    setup_work_chat(db, record)
    configure(db, True)
    invalid = response(db)
    invalid["actions"][0]["party"] = "invalid-party"
    drain(db, model(invalid))
    assert db.rows("SELECT * FROM jobs WHERE status='retry_wait'")
    schedule(db, retry=True)
    drain(db, model(response(db)))
    assert len(db.rows("SELECT * FROM crm_customers")) == 1
