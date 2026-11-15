from contextlib import closing
import json
import httpx
import pytest
from tests.factories import seed_case
from wechat_agent.storage.db import open_db

@pytest.fixture
def model_client(client):
    class Store:
        values={}
        def get(self,ref):return self.values[ref]
        def set(self,ref,value):self.values[ref]=value
    client.app.state.services.credential_store=Store()
    with closing(open_db(client.app.state.database_path)) as db:seed_case(db)
    return client

def config(**updates):
    return dict(account_id='acct-1',expected_version=0,endpoint='https://synthetic.example/chat/completions',model_id='synthetic',response_mode='json_object',context_tokens=16000,max_output_tokens=1000,api_key='private-test-key',**updates)

def test_save_is_secret_free_and_does_not_contact_provider(model_client):
    def forbidden(request):raise AssertionError('saving must not call provider')
    model_client.app.state.services.model_transport=httpx.MockTransport(forbidden)
    result=model_client.put('/api/model',json=config())
    assert result.status_code==200
    assert result.json()['version']==1 and result.json()['connection']['state']=='not_checked'
    assert 'private-test-key' not in result.text and 'credential_ref' not in result.text
    with closing(open_db(model_client.app.state.database_path)) as db:
        assert 'private-test-key' not in db.execute("SELECT value_json FROM settings WHERE name='model_config'").fetchone()[0]
    assert 'api_key' not in model_client.get('/api/model?account_id=acct-1').text

def test_config_conflict_and_endpoint_rotation_require_new_key(model_client):
    assert model_client.put('/api/model',json=config()).status_code==200
    assert model_client.put('/api/model',json=config()).status_code==409
    changed=config();changed.update(expected_version=1,endpoint='https://other.example/chat/completions',api_key=None)
    assert model_client.put('/api/model',json=changed).status_code==422
    changed.update(endpoint='https://synthetic.example/chat/completions',model_id='changed')
    assert model_client.put('/api/model',json=changed).status_code==200

def test_connection_check_is_explicit_and_does_not_claim_capacity(model_client):
    calls=[]
    def reply(request):
        calls.append(request)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"probe":"ok"}'}}]})
    model_client.app.state.services.model_transport=httpx.MockTransport(reply)
    saved=model_client.put('/api/model',json=config()).json();assert calls==[]
    result=model_client.post('/api/model/check',json={'account_id':'acct-1','expected_version':saved['version']})
    assert result.status_code==200
    assert result.json()['connection']['state']=='passed' and result.json()['connection']['capacity_verified'] is False
    assert len(calls)==1 and calls[0].headers['Authorization']=='Bearer private-test-key'
    assert 'private-test-key' not in result.text
    assert model_client.get('/api/settings').json()['model']['connection_state']=='passed'

def test_invalid_and_foreign_requests_do_not_send(model_client):
    assert model_client.put('/api/model',json={**config(),'account_id':'foreign'}).status_code==403
    assert model_client.put('/api/model',json={**config(),'endpoint':'http://insecure.example'}).status_code==422
    assert model_client.post('/api/model/check',json={'account_id':'acct-1','expected_version':0}).status_code==409

def test_failed_probe_does_not_leak_response_or_claim_success(model_client):
    model_client.app.state.services.model_transport=httpx.MockTransport(lambda request:httpx.Response(401,json={'error':'private-test-key'}))
    model_client.put('/api/model',json=config())
    result=model_client.post('/api/model/check',json={'account_id':'acct-1','expected_version':1})
    assert result.status_code==200 and result.json()['connection']['state']=='failed'
    assert 'private-test-key' not in result.text

def test_active_check_is_serialized_and_old_result_cannot_mark_new_config(model_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered=Event();release=Event();calls=[]
    def reply(request):
        calls.append(request);entered.set();assert release.wait(5)
        return httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"probe":"ok"}'}}]})
    model_client.app.state.services.model_transport=httpx.MockTransport(reply)
    model_client.put('/api/model',json=config())
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending=executor.submit(model_client.post,'/api/model/check',json={'account_id':'acct-1','expected_version':1})
        try:
            assert entered.wait(5)
            second=model_client.post('/api/model/check',json={'account_id':'acct-1','expected_version':1})
            assert second.status_code==409 and second.json()['code']=='model_check_running'
            changed=config();changed.update(expected_version=1,model_id='new-model',api_key=None)
            assert model_client.put('/api/model',json=changed).status_code==200
        finally:release.set()
        assert pending.result().status_code==409
    result=model_client.get('/api/model?account_id=acct-1').json()
    assert result['version']==2 and result['connection']['state']=='not_checked' and len(calls)==1

def test_credential_failure_keeps_previous_configuration(model_client):
    from wechat_agent.model.contracts import ModelCallError
    model_client.put('/api/model',json=config())
    class Broken:
        def set(self,*args):raise ModelCallError('credential_unavailable')
    model_client.app.state.services.credential_store=Broken()
    changed=config();changed['expected_version']=1
    assert model_client.put('/api/model',json=changed).status_code==503
    assert model_client.get('/api/model?account_id=acct-1').json()['version']==1

def test_connection_pass_cannot_be_used_as_capacity_verification(model_client):
    from wechat_agent.model.settings import load_runtime_config
    from wechat_agent.model.contracts import ModelCallError
    saved=model_client.put('/api/model',json=config()).json()
    with closing(open_db(model_client.app.state.database_path)) as db:
        with pytest.raises(ModelCallError) as error:load_runtime_config(db,'acct-1',saved['config_version'],None)
        assert error.value.code=='model_capabilities_unverified'

def test_runtime_config_uses_verified_limits_and_saved_version(model_client):
    from datetime import datetime,timezone
    from wechat_agent.model.settings import load_runtime_config
    from wechat_agent.model.contracts import ModelCapabilities
    model_client.app.state.services.model_transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'model':'synthetic','choices':[{'finish_reason':'stop','message':{'content':'{"probe":"ok"}'}}]}))
    saved=model_client.put('/api/model',json=config()).json()
    model_client.post('/api/model/check',json={'account_id':'acct-1','expected_version':1})
    caps=ModelCapabilities(model_id='synthetic',context_tokens=8000,max_output_tokens=500,structured_output=True,vision=False,verified_at=datetime.now(timezone.utc))
    with closing(open_db(model_client.app.state.database_path)) as db:
        runtime=load_runtime_config(db,'acct-1',saved['config_version'],caps)
        assert runtime.version==saved['config_version'] and runtime.capabilities.context_tokens==8000 and runtime.capabilities.max_output_tokens==500

def test_expired_check_is_retryable_in_readonly_status(model_client):
    model_client.put('/api/model',json=config())
    with closing(open_db(model_client.app.state.database_path)) as db,db:
        db.execute("INSERT INTO model_connection_checks(account_id,check_id,config_version,state,started_at,expires_at) VALUES('acct-1','orphan',1,'running',0,1)")
    status=model_client.get('/api/model?account_id=acct-1').json()
    assert status['connection']['state']=='interrupted'
