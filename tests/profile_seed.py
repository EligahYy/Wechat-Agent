"""Synthetic publication fixture, never loaded by production."""
import json
from pathlib import Path
from datetime import datetime,timezone
from wechat_agent.context.builder import build_snapshot
from wechat_agent.source.contracts import ContactKey
from wechat_agent.operations.service import create_operation
from wechat_agent.operations.contracts import OperationScope,CancellationToken
from wechat_agent.profiles.publisher import publish

def seed_profile(conn):
    snapshot=build_snapshot(conn,ContactKey(account_id='acct-1',contact_id='merchant-a'),datetime.now(timezone.utc))
    operation=create_operation(conn,'sync_and_organize',OperationScope(account_id='acct-1',contact_id='merchant-a'),'profile-fixture')
    result=publish(conn,snapshot,json.loads((Path(__file__).parent/'fixtures/profile-ready.json').read_text()),CancellationToken(operation_id=operation.id,generation=operation.generation))
    assert result.version==1,result
    with conn:conn.execute("UPDATE operations SET state='succeeded',phase='completed' WHERE id=?",(operation.id,))
