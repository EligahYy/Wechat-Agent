"""One bounded logical gateway call per discovery window; oversized windows stay pending."""
from importlib.resources import files
import json
from .contracts import DiscoveryResult
from ..model.contracts import ModelRequest,ModelMessage,ModelCallError

class DiscoveryStrategy:
    def __init__(self,conn,gateway):self.conn=conn;self.gateway=gateway
    async def classify(self,snapshot,cancellation):
        saved=self.conn.execute('SELECT manifest_json,payload_json FROM snapshots WHERE account_id=? AND snapshot_id=?',(snapshot.key.account_id,snapshot.id)).fetchone()
        if not saved or json.loads(saved['manifest_json'])!=json.loads(snapshot.model_dump_json()):raise ModelCallError('snapshot_not_authorized')
        prompt=files('wechat_agent.model').joinpath('prompts/business-discovery-v1.md').read_text()
        response=await self.gateway.generate(ModelRequest(call_id='discovery:'+snapshot.id,unit_id='discovery:'+snapshot.id,snapshot_id=snapshot.id,
            purpose='discovery',phase='extract',model_config_version=snapshot.versions['model_config'],messages=[ModelMessage(role='system',content=prompt),ModelMessage(role='user',content=saved['payload_json'])],
            output_schema=DiscoveryResult.model_json_schema(),output_tokens=min(2048,self.gateway.config.capabilities.max_output_tokens)),cancellation)
        result=DiscoveryResult.model_validate(response.payload)
        if result.contact_id!=snapshot.key.contact_id:raise ModelCallError('discovery_target_mismatch')
        return result
