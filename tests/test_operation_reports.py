import pytest
from tests.factories import seed_case
from wechat_agent.operations.contracts import OperationScope
from wechat_agent.operations.service import create_operation,get_operation
from wechat_agent.operations.reports import OperationReport,save_report,load_report


def test_report_and_name_are_account_scoped(db):
    seed_case(db)
    op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'report')
    original=op.contact_name_snapshot
    assert original
    db.execute("UPDATE contacts SET remark='改名' WHERE account_id='acct-1' AND contact_id='merchant-a'")
    report=OperationReport(scope_label=original,source_outcome='completed',analysis_outcome='updated')
    save_report(db,'acct-1',op.id,report)
    assert get_operation(db,'acct-1',op.id).contact_name_snapshot==original
    assert load_report(db,'acct-1',op.id)==report
    assert load_report(db,'other-account',op.id) is None
    with pytest.raises(ValueError):save_report(db,'other-account',op.id,report)


def test_legacy_name_falls_back_without_mutating_snapshot(db):
    seed_case(db)
    op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'legacy-name')
    db.execute('UPDATE operations SET contact_name_snapshot=NULL WHERE id=?',(op.id,))
    db.execute("UPDATE contacts SET remark='最新名字' WHERE account_id='acct-1' AND contact_id='merchant-a'")
    assert get_operation(db,'acct-1',op.id).contact_name_snapshot=='最新名字'
    assert db.execute('SELECT contact_name_snapshot FROM operations WHERE id=?',(op.id,)).fetchone()[0] is None


def test_history_loads_names_and_reports_in_one_query(client,monkeypatch):
    from contextlib import closing
    from wechat_agent.storage.db import open_existing_db
    from wechat_agent.api import operations as endpoint
    with closing(open_existing_db(client.app.state.database_path)) as conn:
        seed_case(conn)
        for i in range(20):
            op=create_operation(conn,'sync',OperationScope(account_id='acct-1'),str(i))
            conn.execute("UPDATE operations SET state='succeeded' WHERE id=?",(op.id,));conn.commit()
    queries=[]
    def traced(*args,**kwargs):
        conn=open_existing_db(*args,**kwargs);conn.set_trace_callback(queries.append);return conn
    monkeypatch.setattr(endpoint,'open_existing_db',traced)
    response=client.get('/api/operations?account_id=acct-1')
    assert response.status_code==200 and len(response.json()['items'])==20
    assert len([q for q in queries if 'operation_reports' in q])==1


def test_analysis_issue_does_not_copy_model_free_text_into_report():
    from wechat_agent.operations.reports import analysis_issue
    issue=analysis_issue('客户原文和敏感信息不应复制到记录','merchant-a')
    assert issue.code=='analysis_review_required'
    assert '敏感信息' not in issue.model_dump_json()
    field=analysis_issue('goods.volume:evidence_invalid','merchant-a')
    assert field.code=='profile_field_invalid' and field.field_path=='goods.volume'


def test_stopped_batch_keeps_completed_contact_but_is_not_reported_complete(db):
    from wechat_agent.operations.reports import finalize_report
    seed_case(db)
    op=create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1'),'stopped-batch')
    db.execute("UPDATE operations SET state='stopped',phase='analysis',error_code='user_stopped' WHERE id=?",(op.id,))
    db.execute("UPDATE operation_items SET state='succeeded' WHERE operation_id=?",(op.id,))
    for person,state,error in [('merchant-a','succeeded',None),('merchant-b','stopped','user_stopped')]:
        db.execute("INSERT INTO operation_items(account_id,operation_id,item_id,contact_id,state,phase,generation,error_code) VALUES('acct-1',?,?,?,?,'analysis',1,?)",(op.id,'analysis:'+person,person,state,error))
    report=finalize_report(db,'acct-1',op.id)
    assert report.analysis_outcome=='stopped'
    assert any(c.contact_id=='merchant-a' and c.analysis_outcome=='updated' for c in report.contacts)
    assert not any(i.severity=='blocker' for i in report.issues)


def test_error_actions_distinguish_transient_failure_from_configuration():
    from wechat_agent.operations.reports import suggested_action
    assert suggested_action('model_timeout')=='retry_sync'
    assert suggested_action('request_invalid')=='open_model_settings'
    assert suggested_action('credential_unavailable')=='open_model_settings'
    assert suggested_action('context_requires_chunking')=='none'
