"""One complete-context candidate call; publication remains an explicit transaction."""
from importlib.resources import files
import json
from pydantic import ValidationError
from ..model.contracts import ModelRequest,ModelMessage,ModelCallError
from ..profiles.contracts import AnalysisResult,analysis_result_schema
from ..profiles.publisher import check_inputs
from ..source.repository import transaction

class WorkflowV1:
    strategy_version="workflow-v1"
    def __init__(self,conn,gateway):
        self.conn=conn;self.gateway=gateway

    async def run(self,snapshot,checkpoint,cancellation):
        if checkpoint:raise ModelCallError('checkpoint_not_supported')
        with transaction(self.conn):
            reader,head,reason=check_inputs(self.conn,snapshot,cancellation)
            if reason:raise ModelCallError(reason)
            if (head['version'] if head else 0)!=snapshot.profile_version:raise ModelCallError('profile_changed')
            if snapshot.versions!={'template':'profile-v1','strategy':'workflow-v1','output_schema':'1','model_config':self.gateway.config.version}:
                raise ModelCallError('workflow_versions_mismatch')
            batches=[{'shipment_id':row['shipment_id'],'stage':row['stage'],'facts':json.loads(row['payload_json']),'numbers':json.loads(row['numbers_json']),'numbers_origin':row['numbers_origin']} for row in self.conn.execute('SELECT * FROM shipments WHERE account_id=? AND contact_id=? ORDER BY shipment_id',(snapshot.key.account_id,snapshot.key.contact_id))]
            payload={'account_id':snapshot.key.account_id,'contact_id':snapshot.key.contact_id,'messages':reader.messages(),'actors':reader.actors(),'conversations':reader.conversations(),'gaps':list(snapshot.gaps),'existing_shipments':batches,'manual_constraints':reader.manual()}
        prompt=files('wechat_agent.model').joinpath('prompts/profile-v1.md').read_text()
        request=ModelRequest(call_id='profile:'+snapshot.id,unit_id='profile:'+snapshot.id,snapshot_id=snapshot.id,purpose='profile',phase='extract',model_config_version=snapshot.versions['model_config'],
            messages=[ModelMessage(role='system',content=prompt),ModelMessage(role='user',content=json.dumps(payload,ensure_ascii=False))],
            output_schema=analysis_result_schema(),output_tokens=min(8192,self.gateway.config.capabilities.max_output_tokens))
        response=await self.gateway.generate(request,cancellation)
        try:result=AnalysisResult.model_validate(response.payload)
        except ValidationError:raise ModelCallError('output_invalid') from None
        if result.contact_id!=snapshot.key.contact_id:raise ModelCallError('target_mismatch')
        return result
