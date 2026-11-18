"""Synthetic publication fixture, never loaded by production."""
import json
import os
from uuid import uuid4
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime,timezone
from wechat_agent.context.builder import build_snapshot
from wechat_agent.source.contracts import ContactKey
from wechat_agent.operations.service import create_operation
from wechat_agent.operations.contracts import OperationScope,CancellationToken
from wechat_agent.profiles.publisher import publish

def seed_profile(conn, *, reuse_published=False):
    snapshot=build_snapshot(conn,ContactKey(account_id='acct-1',contact_id='merchant-a'),datetime.now(timezone.utc), reuse_published=reuse_published)
    operation=SimpleNamespace(id=str(uuid4()),generation=1)
    # A fixture is not a queued user intention: reserve it atomically so the
    # real background worker cannot claim/recover it between creation/publish.
    with conn:
        conn.execute("INSERT INTO operations(account_id,id,contact_id,action,idempotency_key,state,worker_id) VALUES('acct-1',?,'merchant-a','sync_and_organize','profile-fixture','running',?)",(operation.id,f'{os.getpid()}:fixture'))
        conn.execute("INSERT INTO operation_items(account_id,operation_id,item_id,phase,state) VALUES('acct-1',?,'source','source','succeeded')",(operation.id,))
    result=publish(conn,snapshot,json.loads((Path(__file__).parent/'fixtures/profile-ready.json').read_text()),CancellationToken(operation_id=operation.id,generation=operation.generation))
    assert result.version==1,result
    with conn:conn.execute("UPDATE operations SET state='succeeded',phase='completed',worker_id=NULL WHERE id=?",(operation.id,))
