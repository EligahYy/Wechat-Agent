"""Bounded complete-history workflow with durable, input-addressed recovery."""
import asyncio
from dataclasses import asdict
from importlib.resources import files
import json
from ..context.chunks import plan_chunks,MessageSpan,ContextChunk
from ..context.reader import ContextReader
from ..context.assembler import assemble_context
from .adaptive import EXTRACT_MATERIAL_PHASE, pinned_target
from ..context.tokens import request_budget
from ..model.contracts import ModelRequest,ModelMessage,ModelCallError
from ..profiles.contracts import AnalysisResult,analysis_result_schema
from ..profiles.publisher import check_inputs
from ..source.repository import transaction
from .checkpoints import create_run,register_unit,checkpoint,set_unit,RunProgress,unit_cache_key
from .coverage import compute_coverage
from .refinement import supersede,MAX_DEPTH
from .extraction import ExtractedFacts, normalize_extraction
from .reduction import combine_field, record_reduction
from .citations import build_aliases, resolve_aliases, isolate_invalid_fields
from .facts import validate_unit,source_refs,deduplicate,merge_groups,combine,enforce_merge_scope


# Workload targets are independent of provider capacity. Oversized mandatory
# context may exceed the target when it still fits the actual window.
INPUT_TARGET = 24_000


class WorkflowV2:
    strategy_version="workflow-v2"
    def __init__(self,conn,gateway):self.conn=conn;self.gateway=gateway

    def request(self,snapshot,payload,prompt,phase='extract'):
        if payload.get('messages'):
            aliases = build_aliases({(row['message_id'], row['revision']) for row in payload['messages'] if 'message_id' in row and 'revision' in row})
            if aliases:
                by_ref = {ref: alias for alias, ref in aliases.items()}
                payload = {**payload, 'messages': [
                    {**row, 'source_alias': by_ref[(row['message_id'], row['revision'])]}
                    for row in payload['messages']
                ]}
                prompt += '\n引用原文可使用该消息的 source_alias 作为 message_id，revision 保持原值。省略没有证据的字段。'
        uses_sparse_schema = self.strategy_version in {'workflow-v3', 'workflow-v4', 'workflow-v5'} and phase == 'extract'
        if uses_sparse_schema:
            prompt += '\n输出只需包含有证据的字段。若返回 processed_primary_ids，逐一列出主材料消息编号，每个编号只出现一次。'
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
            output_schema=ExtractedFacts.model_json_schema() if uses_sparse_schema else analysis_result_schema(),output_tokens=min(output_target,self.gateway.config.capabilities.max_output_tokens))
        fixed={**payload,**{key:[] for key in ('messages','candidates') if key in payload}}
        probe=request.model_copy(update={'messages':[request.messages[0],ModelMessage(role='user',content=json.dumps(fixed,ensure_ascii=False))]})
        budget=request_budget(probe,self.gateway.config)
        available=budget.context_tokens-budget.safety_tokens-budget.input_tokens-budget.context_tokens//10
        return request.model_copy(update={'output_tokens':min(request.output_tokens,max(16,available))})

    async def unit(self,snapshot,token,request,allowed,label='all',candidates=(),*,reader=None,progress=None,require_coverage=False):
        try:
            saved=checkpoint(self.conn,snapshot,request)
            if saved['state']=='succeeded':
                try:payload=json.loads(saved['output_json'])
                except (ValueError,TypeError):raise ModelCallError('checkpoint_invalid') from None
                result=validate_unit(self.conn,snapshot,payload,allowed,reader=reader)
                enforce_merge_scope(result,label,candidates)
                if require_coverage:
                    record_reduction(self.conn, snapshot, token, label, candidates, result)
                set_unit(self.conn,snapshot,token,request,'succeeded',reused=True,progress=progress)
                return result
            saved_error = saved['error_code']
            if (saved_error in {'output_truncated', 'model_timeout'}
                    or (saved_error == 'history_merge_incomplete' and request.phase == 'merge'
                        and self.strategy_version in {'workflow-v4', 'workflow-v5'} and label != 'shipments')):
                raise ModelCallError(saved_error)
            set_unit(self.conn,snapshot,token,request,'running',progress=progress)
            response=await self.gateway.generate(request,token)
            request_payload = json.loads(request.messages[-1].content)
            aliases = build_aliases({
                (row['message_id'], row['revision']) for row in request_payload.get('messages', [])
            }) if request.phase == 'extract' else {}
            returned = resolve_aliases(response.payload, aliases)
            if request.phase == 'extract':
                primary = request_payload.get('history_unit', {}).get('primary_spans', request_payload.get('messages', []))
                primary_ids = {row['message_id'] for row in primary}
                returned = normalize_extraction(returned, primary_ids, aliases)
            try:result=validate_unit(self.conn,snapshot,returned,allowed,reader=reader)
            except ModelCallError as error:
                if error.code!='chunk_source_outside_unit':raise
                versions={r.message_id:r.revision for r in snapshot.material_refs}
                refs={(r.message_id,r.revision) for r in source_refs(AnalysisResult.model_validate(returned)) if (r.message_id,r.revision) not in allowed}
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
                returned = resolve_aliases(response.payload, aliases)
                if request.phase == 'extract':
                    returned = normalize_extraction(returned, primary_ids, aliases)
                try:
                    result=validate_unit(self.conn,snapshot,returned,allowed,reader=reader)
                except ModelCallError as correction_error:
                    if correction_error.code != 'chunk_source_outside_unit' or request.phase != 'extract':
                        raise
                    parsed = AnalysisResult.model_validate(returned)
                    outside = {r.message_id for r in source_refs(parsed) if (r.message_id, r.revision) not in allowed}
                    if any(self.conn.execute(
                        'SELECT 1 FROM messages WHERE account_id=? AND message_id=?',
                        (snapshot.key.account_id, identifier),
                    ).fetchone() and identifier not in versions for identifier in outside):
                        raise
                    clean = isolate_invalid_fields(parsed, allowed)
                    result = validate_unit(self.conn, snapshot, clean.model_dump(), allowed, reader=reader)
                    if not any(source_refs(result)):
                        raise correction_error
            enforce_merge_scope(result,label,candidates)
            if require_coverage:
                record_reduction(self.conn, snapshot, token, label, candidates, result)
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
            if snapshot.versions!={'template':'profile-v1','strategy':self.strategy_version,'output_schema':'1','model_config':self.gateway.config.version}:
                raise ModelCallError('workflow_versions_mismatch')
            batches=[{'shipment_id':r['shipment_id'],'stage':r['stage'],'facts':json.loads(r['payload_json']),'numbers':json.loads(r['numbers_json']),'numbers_origin':r['numbers_origin']} for r in self.conn.execute('SELECT * FROM shipments WHERE account_id=? AND contact_id=? ORDER BY shipment_id',(snapshot.key.account_id,snapshot.key.contact_id))]
        base={'account_id':snapshot.key.account_id,'contact_id':snapshot.key.contact_id,'actors':reader.actors(),'conversations':reader.conversations(),
            'gaps':list(snapshot.gaps),'existing_shipments':batches,'manual_constraints':reader.manual()}
        rows = reader.messages()
        context_rows = rows
        evidence = None
        review_gaps = []
        if self.strategy_version == 'workflow-v5':
            rows, context_rows, evidence, review_gaps = self.select(snapshot, cancellation, reader, rows, batches)
        prompt=files('wechat_agent.model').joinpath('prompts/profile-v1.md').read_text()
        direct = None
        direct_failed = None
        # Raw body bytes are a lower bound for this estimator. Avoid building
        # and reserializing a full request that cannot meet the direct target.
        if evidence is None and sum(len(row['body'].encode('utf-8')) for row in rows) <= INPUT_TARGET:
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
                if error.code not in {'output_truncated','model_timeout'}:raise
                direct_failed=(ContextChunk(0,tuple(rows),spans,request_budget(req,self.gateway.config)),req)
            if direct_failed is None and not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
            if direct_failed is None:return result
        prompt+='\n'+files('wechat_agent.model').joinpath('prompts/history-v1.md').read_text()
        # Limit metadata to what a chunk can actually observe, without omitting
        # the target or changing the frozen global publication authority.
        def extraction(selected,spans=()):
            pack = assemble_context(base, selected)
            if evidence is not None:
                pack = type(pack)([
                    {**row, 'evidence_allowed': (row['message_id'], row['revision']) in evidence}
                    for row in pack.messages
                ], pack.actors, pack.conversations)

            visible_messages = {row['message_id'] for row in selected}
            rooms = set(pack.conversations)
            # Context gaps for other rooms or unrelated attachments do not
            # affect this extraction's facts or its checkpoint identity.
            scoped_gaps = []
            for gap in base['gaps']:
                code, _, subject = gap.partition(':')
                if code == 'reply_unavailable' and subject in visible_messages:
                    scoped_gaps.append(gap)
                elif code == 'source_message_id_unavailable' and subject in rooms:
                    scoped_gaps.append(gap)
            payload = {
                **base, **asdict(pack), 'existing_shipments': [], 'gaps': scoped_gaps,
                'history_unit': {'phase': 'extract', 'primary_spans': list(spans)},
            }
            return self.request(snapshot,payload,prompt)
        if evidence is not None:
            prompt += '\n只使用 evidence_allowed=true 的原文作为事实引用，其余消息仅解释语境。'
        # Include the primary manifest in planning as well as sending. A span per
        # visible message overestimates context-only metadata, which is safe.
        def planned(selected):
            return extraction(selected,[{'message_id':r['message_id'],'revision':r['revision'],**r.get('body_fragment',{'start':0,'end':len(r['body']),'total':len(r['body'])})} for r in selected])
        create_run(self.conn,snapshot,cancellation,'chunked',self.gateway.config,messages=rows)
        progress = RunProgress(self.conn, snapshot, cancellation)

        async def planned_requests():
            if direct_failed:
                yield direct_failed
                return
            if self.strategy_version in {'workflow-v3', 'workflow-v4', 'workflow-v5'}:
                windows = {}
                for row in rows:
                    key = (row['conversation_id'], row['sent_at'][:7])
                    windows.setdefault(key, []).append(row)
                work = [
                    (room, window, selected) for (room, window), selected in sorted(windows.items())
                ]
            else:
                work = [('', '', rows)]
            ordinal = 0
            for room, window, selected in work:
                target = INPUT_TARGET
                if room:
                    phase = EXTRACT_MATERIAL_PHASE if self.strategy_version in {'workflow-v4', 'workflow-v5'} else 'extract'
                    target = pinned_target(
                        self.conn, snapshot.key.account_id, snapshot.key.contact_id,
                        self.gateway.config.version, room, window, phase=phase,
                    )
                if room and self.strategy_version in {'workflow-v4', 'workflow-v5'}:
                    chunks = await self.material_window(
                        snapshot, room, window, selected, context_rows, planned, extraction, target,
                    )
                else:
                    chunks = await asyncio.to_thread(
                        plan_chunks, selected, planned, self.gateway.config,
                        soft_input_target=target, context_messages=context_rows,
                    )
                requests = []
                for chunk in chunks:
                    req = extraction(list(chunk.messages), [asdict(span) for span in chunk.spans])
                    requests.append((chunk, register_unit(
                        self.conn, snapshot, cancellation, req, chunk.spans, ordinal, self.gateway.config,
                    )))
                    ordinal += 1
                progress.load()
                progress.persist()
                for unit in requests:
                    yield unit
        originals={r['message_id']:r for r in rows}
        refinement_nodes=0
        fatal={'model_cancelled','cancelled','authentication_failed','model_not_found','credential_unavailable','model_config_changed','checkpoint_scope_mismatch','refinement_invalid','analysis_budget_paused','material_changed'}
        async def extract_tree(chunk,req,depth=0):
            nonlocal refinement_nodes
            visible_refs = {(row['message_id'], row['revision']) for row in chunk.messages}
            allowed = visible_refs if evidence is None else visible_refs & evidence
            evidence_rows = [
                row for row in chunk.messages if (row['message_id'], row['revision']) in allowed
            ]
            try:
                return [await self.unit(snapshot, cancellation, req, allowed,
                                        reader=reader.restrict(evidence_rows), progress=progress)]
            except ModelCallError as error:
                if error.code not in {'output_truncated','model_timeout'} or depth>=MAX_DEPTH:raise
            primary=[]
            for span in chunk.spans:
                row=originals[span.message_id]
                primary.append({**row,'body':row['body'][span.start:span.end],
                    'body_fragment':{'start':span.start,'end':span.end,'total':span.total}})
            skeleton=[{**r,'body':''} for r in primary]
            fixed=request_budget(planned(skeleton),self.gateway.config).input_tokens
            variable=request_budget(planned(primary),self.gateway.config).input_tokens-fixed
            limit=fixed+max(128,variable//2)
            try:smaller=await asyncio.to_thread(plan_chunks,primary,planned,self.gateway.config,input_limit=limit,context_messages=context_rows,max_primary_messages=max(1,len(primary)//2))
            except ModelCallError:raise ModelCallError('output_truncated') from None
            if len(smaller)>4 or (len(smaller)==1 and smaller[0].spans==chunk.spans):raise ModelCallError('output_truncated')
            planned_children = [
                (c, extraction(list(c.messages), [asdict(span) for span in c.spans]))
                for c in smaller
            ]
            child_keys = {unit_cache_key(snapshot, request, chunk.spans)
                          for chunk, request in planned_children}
            prior = {}
            for row in self.conn.execute(
                """SELECT e.snapshot_id,p.unit_id,c.cache_key FROM history_refinements e
                   JOIN history_run_units p ON p.account_id=e.account_id
                     AND p.snapshot_id=e.snapshot_id AND p.unit_id=e.parent_id
                   JOIN history_run_units c ON c.account_id=e.account_id
                     AND c.snapshot_id=e.snapshot_id AND c.unit_id=e.child_id
                   WHERE p.account_id=? AND p.contact_id=? AND p.cache_key=?""",
                (snapshot.key.account_id, snapshot.key.contact_id, req.checkpoint_key),
            ):
                prior.setdefault((row[0], row[1]), set()).add(row[2])
            replay = any(keys == child_keys for keys in prior.values())
            if refinement_nodes >= 8 and (not replay or self.strategy_version not in {'workflow-v4', 'workflow-v5'}):
                if self.strategy_version in {'workflow-v4', 'workflow-v5'}:
                    raise ModelCallError('analysis_budget_paused')
                raise ModelCallError('output_truncated')
            children = [register_unit(self.conn, snapshot, cancellation, request, c.spans, c.ordinal, self.gateway.config)
                        for c, request in planned_children]
            supersede(self.conn,snapshot,cancellation,req,children,progress)
            refinement_nodes += int(not replay or self.strategy_version not in {'workflow-v4', 'workflow-v5'})
            results=[];failure=None
            for child,request in zip(smaller,children):
                try:results.extend(await extract_tree(child,request,depth+1))
                except ModelCallError as error:
                    if error.code in fatal:raise
                    failure=failure or error
            if failure:raise failure
            return results
        results=[];first_error=None
        async for chunk,req in planned_requests():
            try:results.extend(await extract_tree(chunk,req))
            except ModelCallError as error:
                if error.code in fatal:raise
                first_error=first_error or error
            await asyncio.sleep(0)
        if first_error:raise first_error
        gaps=sorted({gap for r in results for gap in r.gaps} | set(review_gaps))
        meaningful=[r for r in results if any(source_refs(r))]
        if not meaningful:
            if not compute_coverage(self.conn, snapshot.key.account_id, snapshot.id).complete:
                raise ModelCallError('history_coverage_incomplete')
            return AnalysisResult(contact_id=snapshot.key.contact_id, gaps=gaps)
        if evidence is not None and len(meaningful) == 1:
            if not compute_coverage(self.conn, snapshot.key.account_id, snapshot.id).complete:
                raise ModelCallError('history_coverage_incomplete')
            return meaningful[0].model_copy(update={'gaps': gaps})
        def merge_request(label,candidates):
            return self.request(snapshot,{**base,'history_unit':{'phase':'merge','field':label},'candidates':candidates},prompt,'merge')
        merge_target = pinned_target(
            self.conn, snapshot.key.account_id, snapshot.key.contact_id,
            self.gateway.config.version, '', str(snapshot.profile_version), phase='merge',
        ) if self.strategy_version in {'workflow-v3', 'workflow-v4', 'workflow-v5'} else INPUT_TARGET
        all_candidates=deduplicate(meaningful)
        aggregate_budget = request_budget(merge_request('all', all_candidates), self.gateway.config)
        if aggregate_budget.fits and aggregate_budget.input_tokens <= merge_target:
            groups = [('all', all_candidates)]
        else:groups=merge_groups(meaningful,snapshot.key.contact_id)
        merge_reader = reader if evidence is None else reader.restrict(rows)
        first_error = None
        merge_ordinal = 0

        async def merge_one(label, candidates, *, depth=0, covered=False):
            nonlocal merge_ordinal, progress
            request = merge_request(label, candidates)
            if covered:
                instructions = request.messages[0].model_copy(update={
                    'content': request.messages[0].content + '\n保留每个输入候选的全部来源；不同候选有冲突时保留各方原文，不选定一方。'
                })
                request = request.model_copy(update={'messages': [instructions, *request.messages[1:]]})
            budget = request_budget(request, self.gateway.config)
            too_large = not budget.fits or (label != 'all' and len(candidates) > 1 and budget.input_tokens > merge_target)
            if too_large:
                return await split_merge(label, candidates, depth=depth)
            req = register_unit(self.conn, snapshot, cancellation, request, (), merge_ordinal, self.gateway.config)
            merge_ordinal += 1
            progress.load(merge_only=True,unit_id=req.unit_id)
            progress.persist()
            allowed = {(ref.message_id, ref.revision) for c in candidates
                       for ref in source_refs(AnalysisResult.model_validate(c))}
            try:
                result = await self.unit(snapshot, cancellation, req, allowed, label, candidates,
                                         reader=merge_reader, progress=progress,
                                         require_coverage=covered or self.strategy_version in {'workflow-v4', 'workflow-v5'})
            except ModelCallError as error:
                if error.code not in {'output_truncated', 'model_timeout'} and not (
                    error.code == 'history_merge_incomplete' and self.strategy_version in {'workflow-v4', 'workflow-v5'}
                    and label != 'shipments'
                ):
                    raise
                return await split_merge(label, candidates, depth=depth, parent=req)
            return [(label, result)], [req]

        async def split_merge(label, candidates, *, depth, parent=None):
            if depth >= MAX_DEPTH:
                raise ModelCallError('history_merge_unit_too_large')
            if label == 'all':
                parts = merge_groups([AnalysisResult.model_validate(c) for c in candidates], snapshot.key.contact_id)
                output = []
                units = []
                for field, values in parts:
                    results, children = await merge_one(field, values, depth=depth + 1)
                    output.extend(results)
                    units.extend(children)
            else:
                local = combine_field(label, candidates, snapshot.key.contact_id)
                if local is not None:
                    allowed = {(ref.message_id, ref.revision) for c in candidates
                               for ref in source_refs(AnalysisResult.model_validate(c))}
                    local = validate_unit(self.conn, snapshot, local.model_dump(), allowed, reader=merge_reader)
                    enforce_merge_scope(local, label, candidates)
                    record_reduction(self.conn, snapshot, cancellation, label, candidates, local)
                    output, units = [(label, local)], []
                else:
                    if len(candidates) < 2:
                        raise ModelCallError('history_merge_unit_too_large')
                    pivot = len(candidates) // 2
                    reduced = []
                    units = []
                    for part in (candidates[:pivot], candidates[pivot:]):
                        if len(part) == 1:
                            reduced.extend(part)
                        else:
                            subtree, nodes = await merge_one(label, part, depth=depth + 1, covered=True)
                            reduced.extend(result.model_dump(mode='json', exclude_defaults=True) for _, result in subtree)
                            units.extend(nodes)
                    if len(reduced) >= len(candidates):
                        raise ModelCallError('history_merge_unit_too_large')
                    output, nodes = await merge_one(label, reduced, depth=depth + 1, covered=True)
                    units.extend(nodes)
                    record_reduction(self.conn, snapshot, cancellation, label, candidates, output[0][1])
            if parent is not None:
                if units:
                    supersede(self.conn, snapshot, cancellation, parent, units, progress)
                else:
                    local = combine(output, snapshot.key.contact_id)
                    enforce_merge_scope(local, label, candidates)
                    record_reduction(self.conn, snapshot, cancellation, label, candidates, local)
                    set_unit(self.conn, snapshot, cancellation, parent, 'succeeded',
                             output=local, progress=progress)
                    units = [parent]
            return output, units

        merged = []
        for label, candidates in groups:
            try:
                results_for_group, _ = await merge_one(label, candidates)
                merged.extend(results_for_group)
            except ModelCallError as error:
                if error.code in fatal:
                    raise
                first_error = first_error or error
            await asyncio.sleep(0)
        if first_error:
            raise first_error
        if not compute_coverage(self.conn,snapshot.key.account_id,snapshot.id).complete:raise ModelCallError('history_coverage_incomplete')
        result=combine(merged,snapshot.key.contact_id)
        if self.strategy_version in {'workflow-v4', 'workflow-v5'}:
            timestamps = [item.communication.last_business_at for item in results if item.communication.last_business_at]
            if timestamps:
                result.communication.last_business_at = max(timestamps)
        result.gaps=sorted(set(result.gaps)|set(gaps))
        return result


class WorkflowV3(WorkflowV2):
    """Stable per-conversation windows with feedback-based workload targets."""
    strategy_version = 'workflow-v3'


class WorkflowV4(WorkflowV3):
    strategy_version = 'workflow-v4'

    async def material_window(self, snapshot, room, window, rows, full_history, planned, extraction, target):
        config = self.gateway.config

        async def plan(selected, **limits):
            return await asyncio.to_thread(
                plan_chunks, selected, planned, config, context_messages=full_history, **limits,
            )

        identity = (snapshot.key.account_id, snapshot.key.contact_id)
        previous = self.conn.execute(
            """SELECT target FROM analysis_workload_plans
               WHERE account_id=? AND contact_id=? AND config_version=? AND conversation_id=?
                 AND window_key=? AND phase='extract'""",
            (*identity, config.version, room, window),
        ).fetchone()
        if previous is None:
            return await plan(rows, soft_material_target=target)

        legacy = await plan(rows, soft_input_target=previous[0])
        saved_indices = set()
        fragment_chunks = {}
        for index, chunk in enumerate(legacy):
            for span in chunk.spans:
                if span.start or span.end != span.total:
                    fragment_chunks.setdefault(span.message_id, set()).add(index)
            request = extraction(list(chunk.messages), [asdict(span) for span in chunk.spans])
            key = unit_cache_key(snapshot, request, chunk.spans)
            saved = self.conn.execute(
                """SELECT 1 FROM history_checkpoints WHERE account_id=? AND contact_id=? AND cache_key=?
                   AND (state='succeeded' OR requests>0)""",
                (*identity, key),
            ).fetchone()
            if saved:
                saved_indices.add(index)

        if not saved_indices:
            return await plan(rows, soft_material_target=target)

        # If an attempted unit contains a fragment, keep all units covering
        # that original. Every other original can still be packed whole.
        pending_fragments = list(saved_indices)
        while pending_fragments:
            index = pending_fragments.pop()
            for span in legacy[index].spans:
                neighbours = fragment_chunks.get(span.message_id, set()) - saved_indices
                saved_indices.update(neighbours)
                pending_fragments.extend(neighbours)

        # Preserve exact requests for previously attempted spans. Consecutive
        # unattempted messages can share the larger material allowance.
        positions = {row['message_id']: index for index, row in enumerate(rows)}
        chunks = []
        start = 0
        for index in sorted(saved_indices):
            chunk = legacy[index]
            left = positions[chunk.spans[0].message_id]
            if start < left:
                chunks.extend(await plan(rows[start:left], soft_material_target=target))
            chunks.append(chunk)
            start = positions[chunk.spans[-1].message_id] + 1
        if start < len(rows):
            chunks.extend(await plan(rows[start:], soft_material_target=target))
        return chunks


class WorkflowV5(WorkflowV4):
    strategy_version = 'workflow-v5'

    def __init__(self, conn, gateway, reviewed_refs):
        super().__init__(conn, gateway)
        self.reviewed_refs = reviewed_refs

    async def material_window(self, snapshot, room, window, rows, full_history, planned, extraction, target):
        return await asyncio.to_thread(
            plan_chunks, rows, planned, self.gateway.config,
            context_messages=full_history, soft_material_target=target,
        )

    def select(self, snapshot, token, reader, rows, batches):
        from ..context.relevance import classify_messages
        from .relevance import save_relevance, selected_refs, retained_review_refs, finish_without_model

        authorized = {(ref.message_id, ref.revision) for ref in snapshot.material_refs}
        if not self.reviewed_refs <= authorized:
            raise ModelCallError('relevance_review_material_changed')
        reviewed = self.reviewed_refs | retained_review_refs(self.conn, snapshot)
        manifest = classify_messages(snapshot, rows, reader.actors(), reader.conversations(),
                                     known_batches=batches, reviewed_refs=reviewed)
        save_relevance(self.conn, snapshot, token, manifest)
        if any('revocation_review' in entry.reason_codes for entry in manifest.entries):
            raise ModelCallError('relevance_revocation_review')
        finish_without_model(self.conn, snapshot, token, manifest)
        evidence = selected_refs(snapshot, manifest)
        eligible = {(entry.message_id, entry.revision) for entry in manifest.entries if entry.usable}
        primary = [row for row in rows if (row['message_id'], row['revision']) in evidence]
        context = [row for row in rows if (row['message_id'], row['revision']) in eligible]
        gaps = ['relevance_review_required'] if any(entry.needs_review for entry in manifest.entries) else []
        if not primary:
            raise ModelCallError('relevance_review_required')
        return primary, context, evidence, gaps
