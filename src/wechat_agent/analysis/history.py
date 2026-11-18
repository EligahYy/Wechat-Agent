"""Bounded complete-history workflow with durable, input-addressed recovery."""
import asyncio
from dataclasses import asdict
from importlib.resources import files
import json
from ..context.chunks import plan_chunks,MessageSpan,ContextChunk
from ..context.reader import ContextReader
from ..context.tokens import request_budget
from ..model.contracts import ModelRequest,ModelMessage,ModelCallError
from ..profiles.contracts import AnalysisResult,analysis_result_schema
from ..profiles.publisher import check_inputs
from ..source.repository import transaction
from .checkpoints import create_run,register_unit,checkpoint,set_unit,RunProgress
from .coverage import compute_coverage
from .refinement import supersede,MAX_DEPTH
from .facts import validate_unit,source_refs,deduplicate,merge_groups,combine,enforce_merge_scope


# Workload targets are independent of provider capacity. Oversized mandatory
# context may exceed the target when it still fits the actual window.
INPUT_TARGET = 24_000


class WorkflowV2:
    strategy_version="workflow-v2"
    def __init__(self,conn,gateway):self.conn=conn;self.gateway=gateway

    def request(self,snapshot,payload,prompt,phase='extract'):
        material_key = 'messages' if phase == 'extract' else 'candidates'
        material = payload.get(material_key)
        output_target = 8192
        if material:
            # Workload heuristic, not a token conversion. Include both the
            # number of records and size so dense individual records count.
            material_bytes = len(json.dumps(material, ensure_ascii=False).encode('utf-8'))
            base, per_record = (2048, 64) if phase == 'extract' else (1024, 128)
            output_target = min(8192, base + per_record * len(material) + material_bytes // 16)
        request=ModelRequest(allow_output_growth=True,call_id='planning',unit_id='planning',snapshot_id=snapshot.id,phase=phase,
            model_config_version=self.gateway.config.version,messages=[ModelMessage(role='system',content=prompt),ModelMessage(role='user',content=json.dumps(payload,ensure_ascii=False))],
            output_schema=analysis_result_schema(),output_tokens=min(output_target,self.gateway.config.capabilities.max_output_tokens))
        fixed={**payload,**{key:[] for key in ('messages','candidates') if key in payload}}
        probe=request.model_copy(update={'messages':[request.messages[0],ModelMessage(role='user',content=json.dumps(fixed,ensure_ascii=False))]})
        budget=request_budget(probe,self.gateway.config)
        available=budget.context_tokens-budget.safety_tokens-budget.input_tokens-budget.context_tokens//10
        return request.model_copy(update={'output_tokens':min(request.output_tokens,max(16,available))})

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
            if saved['error_code']=='output_truncated':raise ModelCallError('output_truncated')
            set_unit(self.conn,snapshot,token,request,'running',progress=progress)
            response=await self.gateway.generate(request,token)
            try:result=validate_unit(self.conn,snapshot,response.payload,allowed,reader=reader)
            except ModelCallError as error:
                if error.code!='chunk_source_outside_unit':raise
                versions={r.message_id:r.revision for r in snapshot.material_refs}
                refs={(r.message_id,r.revision) for r in source_refs(AnalysisResult.model_validate(response.payload)) if (r.message_id,r.revision) not in allowed}
                details={'model_source_unknown':0,'model_source_revision_mismatch':0,'model_source_other_unit':0}
                for identifier,revision in refs:
                    key='model_source_unknown' if identifier not in versions else 'model_source_revision_mismatch' if versions[identifier]!=revision else 'model_source_other_unit'
                    details[key]+=1
                with transaction(self.conn):
                    row=self.conn.execute('SELECT counts_json FROM operations WHERE account_id=? AND id=?',(snapshot.key.account_id,token.operation_id)).fetchone()
                    counts=json.loads(row[0])
                    for key,value in details.items():counts[key]=counts.get(key,0)+value
                    self.conn.execute('UPDATE operations SET counts_json=? WHERE account_id=? AND id=?',(json.dumps(counts),snapshot.key.account_id,token.operation_id))
                payload=json.loads(request.messages[-1].content)
                payload['_source_correction']={'instruction':'Return one complete corrected result. Copy message_id and revision exactly from allowed_sources. Remove unsupported facts; do not invent identifiers or use any other sources.','allowed_sources':[{'message_id':identifier,'revision':revision} for identifier,revision in sorted(allowed)]}
                correction=request.model_copy(update={'call_id':request.call_id+':refs','messages':[request.messages[0],ModelMessage(role='user',content=json.dumps(payload,ensure_ascii=False))]})
                if not request_budget(correction,self.gateway.config).fits:raise error
                response=await self.gateway.generate(correction,token)
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
        direct = None
        direct_failed = None
        # Raw body bytes are a lower bound for this estimator. Avoid building
        # and reserializing a full request that cannot meet the direct target.
        if sum(len(row['body'].encode('utf-8')) for row in rows) <= INPUT_TARGET:
            candidate = self.request(snapshot, {**base, 'messages': rows}, prompt)
            direct_budget = request_budget(candidate, self.gateway.config)
            if direct_budget.fits and direct_budget.input_tokens <= INPUT_TARGET:
                direct = candidate
        if direct is not None:
            create_run(self.conn,snapshot,cancellation,'direct',self.gateway.config,messages=rows)
            spans=tuple(MessageSpan(r['message_id'],r['revision'],0,len(r['body']),len(r['body'])) for r in rows)
            req=register_unit(self.conn,snapshot,cancellation,direct,spans,0,self.gateway.config)
            progress=RunProgress(self.conn,snapshot,cancellation);progress.persist()
            try:result=await self.unit(snapshot,cancellation,req,{(r['message_id'],r['revision']) for r in rows},reader=reader,progress=progress)
            except ModelCallError as error:
                if error.code!='output_truncated':raise
                direct_failed=(ContextChunk(0,tuple(rows),spans,request_budget(req,self.gateway.config)),req)
            if direct_failed is None and not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
            if direct_failed is None:return result
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
        create_run(self.conn,snapshot,cancellation,'chunked',self.gateway.config,messages=rows)
        requests=[]
        if direct_failed:requests=[direct_failed]
        else:
            chunks=await asyncio.to_thread(
                plan_chunks, rows, planned, self.gateway.config,
                soft_input_target=INPUT_TARGET,
            )
            for chunk in chunks:
                req=extraction(list(chunk.messages),[asdict(s) for s in chunk.spans])
                requests.append((chunk,register_unit(self.conn,snapshot,cancellation,req,chunk.spans,chunk.ordinal,self.gateway.config)))
        progress=RunProgress(self.conn,snapshot,cancellation);progress.persist()
        originals={r['message_id']:r for r in rows}
        refinement_nodes=0
        fatal={'model_cancelled','cancelled','authentication_failed','model_not_found','credential_unavailable','model_config_changed','checkpoint_scope_mismatch','refinement_invalid'}
        async def extract_tree(chunk,req,depth=0):
            nonlocal refinement_nodes
            try:return [await self.unit(snapshot,cancellation,req,{(r['message_id'],r['revision']) for r in chunk.messages},reader=reader,progress=progress)]
            except ModelCallError as error:
                if error.code!='output_truncated' or depth>=MAX_DEPTH or refinement_nodes>=8:raise
            primary=[]
            for span in chunk.spans:
                row=originals[span.message_id]
                primary.append({**row,'body':row['body'][span.start:span.end],
                    'body_fragment':{'start':span.start,'end':span.end,'total':span.total}})
            skeleton=[{**r,'body':''} for r in primary]
            fixed=request_budget(planned(skeleton),self.gateway.config).input_tokens
            variable=request_budget(planned(primary),self.gateway.config).input_tokens-fixed
            limit=fixed+max(128,variable//2)
            try:smaller=await asyncio.to_thread(plan_chunks,primary,planned,self.gateway.config,input_limit=limit,context_messages=rows,max_primary_messages=max(1,len(primary)//2))
            except ModelCallError:raise ModelCallError('output_truncated') from None
            if len(smaller)>4 or (len(smaller)==1 and smaller[0].spans==chunk.spans):raise ModelCallError('output_truncated')
            children=[register_unit(self.conn,snapshot,cancellation,extraction(list(c.messages),[asdict(s) for s in c.spans]),c.spans,c.ordinal,self.gateway.config) for c in smaller]
            supersede(self.conn,snapshot,cancellation,req,children,progress)
            refinement_nodes+=1
            results=[];failure=None
            for child,request in zip(smaller,children):
                try:results.extend(await extract_tree(child,request,depth+1))
                except ModelCallError as error:
                    if error.code in fatal:raise
                    failure=failure or error
            if failure:raise failure
            return results
        results=[];first_error=None
        for chunk,req in requests:
            try:results.extend(await extract_tree(chunk,req))
            except ModelCallError as error:
                if error.code in fatal:raise
                first_error=first_error or error
            await asyncio.sleep(0)
        if first_error:raise first_error
        gaps=sorted({gap for r in results for gap in r.gaps})
        meaningful=[r for r in results if any(source_refs(r))]
        if not meaningful:
            if not compute_coverage(self.conn, snapshot.key.account_id, snapshot.id).complete:
                raise ModelCallError('history_coverage_incomplete')
            return AnalysisResult(contact_id=snapshot.key.contact_id, gaps=gaps)
        def merge_request(label,candidates):
            return self.request(snapshot,{**base,'history_unit':{'phase':'merge','field':label},'candidates':candidates},prompt,'merge')
        all_candidates=deduplicate(meaningful)
        aggregate_budget = request_budget(merge_request('all', all_candidates), self.gateway.config)
        if aggregate_budget.fits and aggregate_budget.input_tokens <= INPUT_TARGET:
            groups = [('all', all_candidates)]
        else:groups=merge_groups(meaningful,snapshot.key.contact_id)
        merges=[]
        merged=[]
        for ordinal,(label,candidates) in enumerate(groups):
            req=merge_request(label,candidates)
            if not request_budget(req,self.gateway.config).fits:
                # merge_groups already coalesces equal field values including
                # all their validated references. A single fact needs no model.
                if len(candidates) == 1 and label.startswith(('goods.', 'logistics.')):
                    merged.append((label, AnalysisResult.model_validate(candidates[0])))
                    continue
                raise ModelCallError('history_merge_unit_too_large')
            merges.append((label,candidates,register_unit(self.conn,snapshot,cancellation,req,(),ordinal,self.gateway.config)))
        progress.load(merge_only=True);progress.persist()
        first_error=None
        async def merge_one(label,candidates,req):
            allowed={(ref.message_id,ref.revision) for c in candidates for ref in source_refs(AnalysisResult.model_validate(c))}
            try:return [(label,await self.unit(snapshot,cancellation,req,allowed,label,candidates,reader=reader,progress=progress))]
            except ModelCallError as error:
                if error.code!='output_truncated' or label!='all':raise
            split=merge_groups([AnalysisResult.model_validate(c) for c in candidates],snapshot.key.contact_id)
            child_requests=[]
            for index,(field,values) in enumerate(split):
                child=merge_request(field,values)
                if not request_budget(child,self.gateway.config).fits:raise ModelCallError('history_merge_unit_too_large')
                child_requests.append(register_unit(self.conn,snapshot,cancellation,child,(),index,self.gateway.config))
            supersede(self.conn,snapshot,cancellation,req,child_requests,progress)
            out=[];failure=None
            for (field,values),child in zip(split,child_requests):
                try:out.extend(await merge_one(field,values,child))
                except ModelCallError as error:
                    if error.code in fatal:raise
                    failure=failure or error
            if failure:raise failure
            return out
        for label,candidates,req in merges:
            try:merged.extend(await merge_one(label,candidates,req))
            except ModelCallError as error:
                if error.code in fatal:raise
                first_error=first_error or error
            await asyncio.sleep(0)
        if first_error:raise first_error
        if not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
        result=combine(merged,snapshot.key.contact_id)
        result.gaps=sorted(set(result.gaps)|set(gaps))
        return result
