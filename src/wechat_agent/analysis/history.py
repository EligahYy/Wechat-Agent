"""Bounded complete-history workflow with durable, input-addressed recovery."""
import asyncio
from dataclasses import asdict
from importlib.resources import files
import json
from ..context.chunks import plan_chunks,MessageSpan
from ..context.reader import ContextReader
from ..context.tokens import request_budget
from ..model.contracts import ModelRequest,ModelMessage,ModelCallError
from ..profiles.contracts import AnalysisResult,analysis_result_schema
from ..profiles.publisher import check_inputs
from ..source.repository import transaction
from .checkpoints import create_run,register_unit,checkpoint,set_unit,RunProgress
from .coverage import compute_coverage
from .facts import validate_unit,source_refs,deduplicate,merge_groups,combine,enforce_merge_scope


class WorkflowV2:
    strategy_version="workflow-v2"
    def __init__(self,conn,gateway):self.conn=conn;self.gateway=gateway

    def request(self,snapshot,payload,prompt,phase='extract'):
        return ModelRequest(call_id='planning',unit_id='planning',snapshot_id=snapshot.id,phase=phase,
            model_config_version=self.gateway.config.version,messages=[ModelMessage(role='system',content=prompt),ModelMessage(role='user',content=json.dumps(payload,ensure_ascii=False))],
            output_schema=analysis_result_schema(),output_tokens=min(8192,self.gateway.config.capabilities.max_output_tokens))

    async def unit(self,snapshot,token,request,allowed,label='all',candidates=(),*,reader=None,progress=None):
        try:
            saved=checkpoint(self.conn,snapshot,request)
            if saved['state']=='succeeded':
                try:payload=json.loads(saved['output_json'])
                except (ValueError,TypeError):raise ModelCallError('checkpoint_invalid') from None
                result=validate_unit(self.conn,snapshot,payload,allowed,reader=reader)
                enforce_merge_scope(result,label,candidates)
                set_unit(self.conn,snapshot,token,request,'succeeded',reused=True,progress=progress)
                return result
            set_unit(self.conn,snapshot,token,request,'running',progress=progress)
            response=await self.gateway.generate(request,token)
            result=validate_unit(self.conn,snapshot,response.payload,allowed,reader=reader)
            enforce_merge_scope(result,label,candidates)
            set_unit(self.conn,snapshot,token,request,'succeeded',output=result,progress=progress)
            return result
        except ModelCallError as error:
            if error.code in {'model_cancelled','cancelled'}:raise
            set_unit(self.conn,snapshot,token,request,'failed',error=error.code,progress=progress)
            raise

    async def run(self,snapshot,checkpoint_hint,cancellation):
        if checkpoint_hint:raise ModelCallError('checkpoint_not_supported')
        with transaction(self.conn):
            reader,head,reason=check_inputs(self.conn,snapshot,cancellation)
            if reason:raise ModelCallError(reason)
            if (head['version'] if head else 0)!=snapshot.profile_version:raise ModelCallError('profile_changed')
            if snapshot.versions!={'template':'profile-v1','strategy':'workflow-v2','output_schema':'1','model_config':self.gateway.config.version}:
                raise ModelCallError('workflow_versions_mismatch')
            batches=[{'shipment_id':r['shipment_id'],'stage':r['stage'],'facts':json.loads(r['payload_json']),'numbers':json.loads(r['numbers_json']),'numbers_origin':r['numbers_origin']} for r in self.conn.execute('SELECT * FROM shipments WHERE account_id=? AND contact_id=? ORDER BY shipment_id',(snapshot.key.account_id,snapshot.key.contact_id))]
        base={'account_id':snapshot.key.account_id,'contact_id':snapshot.key.contact_id,'actors':reader.actors(),'conversations':reader.conversations(),
            'gaps':list(snapshot.gaps),'existing_shipments':batches,'manual_constraints':reader.manual()}
        rows=reader.messages()
        prompt=files('wechat_agent.model').joinpath('prompts/profile-v1.md').read_text()
        direct=self.request(snapshot,{**base,'messages':rows},prompt)
        if request_budget(direct,self.gateway.config).fits:
            create_run(self.conn,snapshot,cancellation,'direct',self.gateway.config,messages=rows)
            spans=tuple(MessageSpan(r['message_id'],r['revision'],0,len(r['body']),len(r['body'])) for r in rows)
            req=register_unit(self.conn,snapshot,cancellation,direct,spans,0,self.gateway.config)
            progress=RunProgress(self.conn,snapshot,cancellation);progress.persist()
            result=await self.unit(snapshot,cancellation,req,{(r['message_id'],r['revision']) for r in rows},reader=reader,progress=progress)
            if not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
            return result
        prompt+='\n'+files('wechat_agent.model').joinpath('prompts/history-v1.md').read_text()
        # Limit metadata to what a chunk can actually observe, without omitting
        # the target or changing the frozen global publication authority.
        def extraction(selected,spans=()):
            senders={r['sender_id'] for r in selected}|{snapshot.key.contact_id}
            rooms={r['conversation_id'] for r in selected}
            payload={**base,'actors':{k:v for k,v in base['actors'].items() if k in senders},'conversations':{k:v for k,v in base['conversations'].items() if k in rooms},
                'messages':selected,'existing_shipments':[],
                'history_unit':{'phase':'extract','primary_spans':list(spans)}}
            return self.request(snapshot,payload,prompt)
        # Include the primary manifest in planning as well as sending. A span per
        # visible message overestimates context-only metadata, which is safe.
        def planned(selected):
            return extraction(selected,[{'message_id':r['message_id'],'revision':r['revision'],**r.get('body_fragment',{'start':0,'end':len(r['body']),'total':len(r['body'])})} for r in selected])
        chunks=await asyncio.to_thread(plan_chunks,rows,planned,self.gateway.config)
        create_run(self.conn,snapshot,cancellation,'chunked',self.gateway.config,messages=rows)
        requests=[]
        for chunk in chunks:
            req=extraction(list(chunk.messages),[asdict(s) for s in chunk.spans])
            requests.append((chunk,register_unit(self.conn,snapshot,cancellation,req,chunk.spans,chunk.ordinal,self.gateway.config)))
        progress=RunProgress(self.conn,snapshot,cancellation);progress.persist()
        results=[];first_error=None
        fatal={'model_cancelled','cancelled','authentication_failed','model_not_found','credential_unavailable','model_config_changed','checkpoint_scope_mismatch'}
        for chunk,req in requests:
            try:results.append(await self.unit(snapshot,cancellation,req,{(r['message_id'],r['revision']) for r in chunk.messages},reader=reader,progress=progress))
            except ModelCallError as error:
                if error.code in fatal:raise
                first_error=first_error or error
            await asyncio.sleep(0)
        if first_error:raise first_error
        gaps=sorted({gap for r in results for gap in r.gaps})
        meaningful=[r for r in results if any(source_refs(r))]
        if not meaningful:return AnalysisResult(contact_id=snapshot.key.contact_id,gaps=gaps)
        def merge_request(label,candidates):
            return self.request(snapshot,{**base,'history_unit':{'phase':'merge','field':label},'candidates':candidates},prompt,'merge')
        all_candidates=deduplicate(meaningful)
        if request_budget(merge_request('all',all_candidates),self.gateway.config).fits:groups=[('all',all_candidates)]
        else:groups=merge_groups(meaningful,snapshot.key.contact_id)
        merges=[]
        for ordinal,(label,candidates) in enumerate(groups):
            req=merge_request(label,candidates)
            if not request_budget(req,self.gateway.config).fits:raise ModelCallError('history_merge_unit_too_large')
            merges.append((label,candidates,register_unit(self.conn,snapshot,cancellation,req,(),ordinal,self.gateway.config)))
        progress.load(merge_only=True);progress.persist()
        merged=[];first_error=None
        for label,candidates,req in merges:
            allowed={(ref.message_id,ref.revision) for c in candidates for ref in source_refs(AnalysisResult.model_validate(c))}
            try:merged.append((label,await self.unit(snapshot,cancellation,req,allowed,label,candidates,reader=reader,progress=progress)))
            except ModelCallError as error:
                if error.code in fatal:raise
                first_error=first_error or error
            await asyncio.sleep(0)
        if first_error:raise first_error
        if not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
        result=combine(merged,snapshot.key.contact_id)
        result.gaps=sorted(set(result.gaps)|set(gaps))
        return result
