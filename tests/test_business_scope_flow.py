import pytest
from tests.factories import seed_case
from tests.test_business_scope import KEY
from wechat_agent.contacts.scope import set_scope
from wechat_agent.operations.contracts import OperationScope
from wechat_agent.operations.service import create_operation,OperationError
from wechat_agent.operations.worker import run_next
from wechat_agent.services import Services
from tests.fakes.source import FakeSource

def test_single_excluded_merchant_requires_explicit_reinclude(db):
    seed_case(db);set_scope(db,[KEY],False,{'merchant-a':0})
    with pytest.raises(OperationError,match='contact_scope_excluded'):
        create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'excluded')

@pytest.mark.asyncio
async def test_global_sync_keeps_source_discovery_but_excludes_analysis_target(db):
    seed_case(db);set_scope(db,[KEY],False,{'merchant-a':0})
    create_operation(db,'sync_and_organize',OperationScope(account_id='acct-1'),'global')
    job=await run_next(db,Services(source=FakeSource(),auto_run=False))
    assert not db.execute("SELECT 1 FROM operation_items WHERE contact_id='merchant-a' AND phase='analysis'").fetchone()
    assert job.counts['pages_processed']>0
