"""Version-frozen production model session, opened only for explicit operations."""
import httpx
from ..model.settings import read_saved,load_runtime_config
from ..model.budget import reviewed_capabilities
from ..model.contracts import ModelCallError
from ..model.gateway import ModelGateway
from ..model.credentials import CredentialStore
from .history import WorkflowV2
from ..discovery.classifier import DiscoveryStrategy

class RuntimeSession:
    def __init__(self,conn,account,services):
        saved,version=read_saved(conn,account)
        if not saved:raise ModelCallError('capability_not_ready')
        self.config=load_runtime_config(conn,account,saved['config_version'],reviewed_capabilities(conn,account,version))
        self.conn=conn;self.services=services
    async def __aenter__(self):
        self.client=httpx.AsyncClient(transport=self.services.model_transport,trust_env=False)
        gateway=ModelGateway(self.conn,self.config,self.client,self.services.credential_store or CredentialStore())
        self.workflow=WorkflowV2(self.conn,gateway)
        self.discovery=DiscoveryStrategy(self.conn,gateway)
        return self
    async def __aexit__(self,*args):await self.client.aclose()
