"""Strict synthetic scenario inputs. These files never contain real chat data."""
import json
from pathlib import Path
from pydantic import BaseModel,ConfigDict

GIVEN_KEYS=set('unrelated_group_membership target_membership author_proven_room private_exists room_failure global_failure scope second_merchant inserted prior_profile same_inputs model_config_version_delta manual_version_delta messages model_failure fail_during_model model_response context_size during_model old_goods model_omits_goods old_evidence_authorizable same_name_contact rename_after_creation record_only legacy_report legacy_state contact_deleted duplicate_idempotency_key role business_override stop_before_start legacy_counts_completed legacy_counts_total provisional_business_lead discovery_failure action source_missing_rooms'.split())

def load_cases(path=None):
    payload=json.loads(Path(path or Path(__file__).parent/'fixtures/organize-scenarios.json').read_text())
    assert payload['version']==1
    ids=set()
    for case in payload['cases']:
        if case['id'] in ids:raise ValueError('duplicate_case')
        ids.add(case['id'])
        unknown=set(case['given'])-GIVEN_KEYS
        if unknown:raise ValueError('unknown_scenario_field:'+','.join(sorted(unknown)))
        yield case

async def run_scenario(conn,case):
    """Exercise real sync/worker/snapshot/workflow/publication with synthetic I/O."""
    from types import SimpleNamespace
    from copy import deepcopy
    from datetime import datetime,timezone
    from tests.fakes.source import FakeSource
    from tests.factories import make_message,make_page
    from wechat_agent.source.contracts import ContactKey,ContactRecord,ConversationRecord
    from wechat_agent.source.repository import archive_metadata,archive_page,transaction
    from wechat_agent.operations.service import create_operation,control_operation,get_operation,OperationError
    from wechat_agent.operations.contracts import OperationScope
    from wechat_agent.operations.worker import run_next
    from wechat_agent.services import Services
    from wechat_agent.analysis.workflow import WorkflowV1
    from wechat_agent.model.contracts import ModelCallError
    from wechat_agent.source.adapter import SourceError
    g=deepcopy(case['given']);account='acct-1';contact='merchant-a';calls=[]
    people=[ContactRecord(key=ContactKey(account_id=account,contact_id=i),remark='兴🌟' if i==contact else i,nickname=None,is_self=False) for i in (contact,'merchant-b','provider-a')]
    rooms=[]
    private=g.get('private_exists',True)
    if private:rooms.append(ConversationRecord(account_id=account,conversation_id=contact,kind='private',title='私聊',member_ids=[contact]))
    related=g.get('target_membership','known')=='known'
    room=ConversationRecord(account_id=account,conversation_id='room-a',kind='group',title='A群',membership_state='known' if related else 'unknown',member_ids=[contact] if related else [])
    rooms.append(room)
    messages=g.get('messages',[{'id':'a1','room':'room-a','sender':contact,'body':'下周发德国，20方服装','revision':1},{'id':'a2','room':'room-a','sender':'provider-a','body':'请确认地址','revision':1}])
    if not related and not g.get('author_proven_room',True):messages=[m for m in messages if m['sender']!=contact]
    if g.get('second_merchant'):
        b=g['second_merchant']
        for name in b['rooms']:
            if name=='room-a':room.member_ids.append('merchant-b')
            else:rooms.append(ConversationRecord(account_id=account,conversation_id=name,kind='group',title='B群',membership_state='known',member_ids=['merchant-b']))
            messages.append({'id':'b1','room':name,'sender':'merchant-b','body':'德国20方服装','revision':1})
    if g.get('same_name_contact'):
        people[1]=people[1].model_copy(update={'remark':'兴🌟'})
    if g.get('context_size')=='over_budget':messages[0]['body']+='X'*600000+'TAIL-MUST-REMAIN'
    records=[make_message(message_id=m['id'],conversation_id=m['room'],sender_id=m['sender'],body=m['body'],sent_at=datetime(2026,11,16,12,tzinfo=timezone.utc)) for m in messages]
    if case['expect'].get('foreign_account_unchanged'):
        foreign='foreign-acct'
        archive_metadata(conn,foreign,[ContactRecord(key=ContactKey(account_id=foreign,contact_id='foreign-person'),remark='foreign sentinel',nickname=None,is_self=False)],[ConversationRecord(account_id=foreign,conversation_id='foreign-person',kind='private',title='foreign')])
        archive_page(conn,make_page([make_message(account_id=foreign,conversation_id='foreign-person',message_id='foreign-message',sender_id='foreign-person')],account_id=foreign,conversation_id='foreign-person',conversation_kind='private'))
        foreign_before=[tuple(r) for r in conn.execute('SELECT * FROM messages WHERE account_id=?',(foreign,))]
    archive_metadata(conn,account,people,rooms)
    with transaction(conn):
        for p in people:conn.execute("UPDATE contacts SET role=?,role_version=1 WHERE account_id=? AND contact_id=?",('provider' if p.key.contact_id=='provider-a' else g.get('role','merchant') if p.key.contact_id==contact else 'merchant',account,p.key.contact_id))
    pages={r.conversation_id:[make_page([m for m in records if m.conversation_id==r.conversation_id],conversation_id=r.conversation_id,conversation_kind=r.kind)] for r in rooms}
    for page in pages.values():archive_page(conn,page[0])
    if g.get('unrelated_group_membership'):
        rooms.append(ConversationRecord(account_id=account,conversation_id='unrelated',kind='group',title='未知群',membership_state=g['unrelated_group_membership']))
        pages['unrelated']=[make_page([],conversation_id='unrelated')]
    class Source(FakeSource):
        def __init__(self):
            super().__init__();self.people=people;self.rooms=rooms;self.pages=pages
        async def refresh_metadata(self):
            if g.get('global_failure') and g['global_failure'] not in {'source_metadata_changed','source_changed_during_sync','archive_write_failed'}:raise SourceError(g['global_failure'])
        async def messages(self,room_id,cursor,limit):
            if room_id=='room-a' and g.get('global_failure') in {'source_metadata_changed','source_changed_during_sync'}:
                assert conn.execute("SELECT COUNT(*) FROM sync_attempts WHERE account_id=? AND state='succeeded'",(account,)).fetchone()[0]>0
                raise SourceError(g['global_failure'])
            if room_id=='room-a' and g.get('global_failure')=='archive_write_failed':
                conn.execute("CREATE TEMP TRIGGER scenario_write_failure BEFORE INSERT ON message_revisions WHEN NEW.message_id='failing-new' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
                return make_page([make_message(message_id='failing-new',conversation_id=room_id,body='新消息写入回滚')],conversation_id=room_id)
            if g.get('room_failure',{}).get(room_id)=='message_sender_conflict':
                from wechat_agent.source.contracts import SourceIssue
                return make_page([],conversation_id=room_id,complete=False,gaps=['message_sender_conflict'],issues=[SourceIssue(code='message_sender_conflict',message_id='conflicted-new',raw={'talker':room_id,'sender_candidate':'merchant-a','sender_fallback':'provider-a','content':'synthetic conflict'})])
            if room_id in g.get('room_failure',{}):raise SourceError(g['room_failure'][room_id])
            return await super().messages(room_id,cursor,limit)
    source=Source()
    session=None
    class Gateway:
        def __init__(self,db):self.db=db;self.config=SimpleNamespace(version='1',capabilities=SimpleNamespace(max_output_tokens=8192))
        async def generate(self,request,token,*,deadline=None):
            if g.get('context_size')=='over_budget':
                assert 'TAIL-MUST-REMAIN' in request.messages[-1].content
                raise ModelCallError('context_requires_chunking')
            calls.append(request)
            if g.get('fail_during_model'):raise ModelCallError(g['model_failure'])
            data=json.loads(request.messages[-1].content);target=data['contact_id']
            own=[m for m in data['messages'] if m['sender_id']==target]
            ref={'message_id':own[0]['message_id'],'revision':own[0]['revision']}
            if g.get('model_response')=='foreign_account_citation':ref={'message_id':'foreign-message','revision':1}
            fact={'state':'known','value':g.get('old_goods','服装'),'sources':[ref]}
            result={'contact_id':target,'goods':{'category':fact},'communication':{'summary':{'state':'known','value':'下周发德国服装','sources':[ref]}}}
            if g.get('model_omits_goods'):result.pop('goods')
            during=g.get('during_model')
            if during:
                with transaction(self.db):
                    if during=='manual_version_delta':self.db.execute("INSERT INTO profile_heads(account_id,contact_id,manual_version) VALUES(?,?,1) ON CONFLICT(account_id,contact_id) DO UPDATE SET manual_version=manual_version+1",(account,target))
                    elif during=='role_version_delta':self.db.execute('UPDATE contacts SET role_version=role_version+1 WHERE account_id=? AND contact_id=?',(account,target))
                    elif during=='scope_version_delta':self.db.execute("INSERT INTO business_scope_overrides(account_id,contact_id,included,version) VALUES(?,?,0,1)",(account,target))
                    elif during=='message_revision_delta':self.db.execute('UPDATE messages SET revision=revision+1 WHERE account_id=? AND message_id=?',(account,ref['message_id']))
                if during=='stop':control_operation(self.db,account,token.operation_id,'stop')
            return SimpleNamespace(payload=result)
    class Session:
        def __init__(self,db):
            self.gateway=Gateway(db);self.config=self.gateway.config;self.workflow=WorkflowV1(db,self.gateway);self.discovery=self
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def classify(self,*args):calls.append('discovery');raise ModelCallError('model_timeout')
    def factory(db,acct):
        nonlocal session
        if g.get('model_failure') and not g.get('fail_during_model'):raise ModelCallError(g['model_failure'])
        session=Session(db)
        if g.get('model_config_version_delta'):session.config.version='2'
        return session
    services=Services(source=source,analysis_factory=factory)
    scope=OperationScope(account_id=account,contact_id=None if g.get('scope')=='account' else contact)
    async def execute(key,action='sync_and_organize'):
        op=create_operation(conn,action,scope if action!='refresh_contacts' else OperationScope(account_id=account),key)
        if g.get('rename_after_creation'):
            source.people=[p.model_copy(update={'remark':g['rename_after_creation']}) if p.key.contact_id==contact else p for p in source.people]
        return await run_next(conn,services)
    if g.get('prior_profile'):
        saved=deepcopy(g)
        for k in ('model_omits_goods','old_evidence_authorizable','during_model','context_size','model_response','model_failure','fail_during_model','model_config_version_delta'):g.pop(k,None)
        await execute('prior');calls.clear();g.clear();g.update(saved)
        if g.get('model_omits_goods') or g.get('old_evidence_authorizable') is False:
            with transaction(conn):conn.execute("UPDATE contacts SET role_version=role_version+1 WHERE account_id=? AND contact_id=?",(account,contact))
        if g.get('old_evidence_authorizable') is False:
            revised=next(m for m in records if m.message_id=='a1').model_copy(update={'body':'修订后的服装需求','source_revision':'changed'})
            archive_page(conn,make_page([revised],conversation_id='room-a',conversation_kind='group'))
            pages['room-a'][0]=pages['room-a'][0].model_copy(update={'records':[revised if m.message_id=='a1' else m for m in pages['room-a'][0].records]})
    before=conn.execute('SELECT COALESCE(SUM(version),0) FROM profile_heads WHERE account_id=?',(account,)).fetchone()[0]
    if g.get('manual_version_delta'):
        from wechat_agent.profiles.manual import save_manual
        save_manual(conn,ContactKey(account_id=account,contact_id=contact),{'fields':{'goods.category':'人工服装'}},0)
    if g.get('source_missing_rooms'):source.rooms=[r for r in rooms if r.conversation_id not in g['source_missing_rooms']]
    if g.get('record_only'):
        op=create_operation(conn,'sync_and_organize',scope,'legacy')
        if g.get('contact_deleted'):conn.execute('PRAGMA foreign_keys=OFF')
        with transaction(conn):
            conn.execute("UPDATE operations SET state='failed',contact_name_snapshot=NULL,counts_json=? WHERE account_id=? AND id=?",(json.dumps({'completed_conversations':g.get('legacy_counts_completed',0),'conversations_total':g.get('legacy_counts_total',0)}),account,op.id))
            if g.get('contact_deleted'):conn.execute("UPDATE operations SET contact_id='deleted-person' WHERE account_id=? AND id=?",(account,op.id))
            conn.execute("UPDATE operation_items SET state='failed' WHERE account_id=? AND operation_id=?",(account,op.id))
        conn.execute('PRAGMA foreign_keys=ON')
        op=get_operation(conn,account,op.id)
        if g.get('contact_deleted'):assert op.contact_name_snapshot is None
        assert op.counts['completed_conversations']==g.get('legacy_counts_completed',0)
        assert not calls and not source.calls
        return dict(source_outcome='failed' if op.source_state=='failed' else 'not_started',analysis_outcome='not_started',model_calls=len(calls),publish=False,operation=op)
    if g.get('business_override')=='exclude':
        with transaction(conn):conn.execute('INSERT INTO business_scope_overrides(account_id,contact_id,included,version) VALUES(?,?,0,1)',(account,contact))
        try:create_operation(conn,'sync_and_organize',scope,'excluded')
        except OperationError as error:
            assert str(error)=='contact_scope_excluded'
            return dict(source_outcome='not_started',analysis_outcome='not_applicable',model_calls=0,publish=False,operation=None)
        raise AssertionError('manual exclusion was ignored')
    if g.get('duplicate_idempotency_key'):
        first=create_operation(conn,'sync_and_organize',scope,'current')
        assert create_operation(conn,'sync_and_organize',scope,'current').id==first.id
        op=await run_next(conn,services)
    elif g.get('stop_before_start'):
        op=create_operation(conn,'sync_and_organize',scope,'current');control_operation(conn,account,op.id,'stop');op=get_operation(conn,account,op.id)
    else:op=await execute('current',g.get('action','sync_and_organize'))
    after=conn.execute('SELECT COALESCE(SUM(version),0) FROM profile_heads WHERE account_id=?',(account,)).fetchone()[0]
    if g.get('manual_version_delta'):
        from wechat_agent.profiles.manual import read_profile
        assert read_profile(conn,ContactKey(account_id=account,contact_id=contact))['effective']['goods']['category']['value']=='人工服装'
    if case['expect'].get('foreign_account_unchanged'):assert [tuple(r) for r in conn.execute('SELECT * FROM messages WHERE account_id=?',(foreign,))]==foreign_before
    if case['expect'].get('no_half_transaction'):
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE account_id=? AND message_id='failing-new'",(account,)).fetchone()[0]==0
        assert conn.execute("SELECT COUNT(*) FROM message_revisions WHERE account_id=? AND message_id='failing-new'",(account,)).fetchone()[0]==0
    if case['expect'].get('quarantine'):assert conn.execute('SELECT COUNT(*) FROM source_issues WHERE account_id=?',(account,)).fetchone()[0]>0
    if case['expect'].get('head_unchanged'):assert after==before
    if case['expect'].get('history_label'):assert op.contact_name_snapshot==case['expect']['history_label']
    if case['expect'].get('retained_goods'):
        payload=json.loads(conn.execute('SELECT result_json FROM profile_versions WHERE account_id=? AND contact_id=? ORDER BY version DESC LIMIT 1',(account,contact)).fetchone()[0])
        assert payload['goods']['category']['value']==case['expect']['retained_goods']
    if case['expect'].get('context_contains_other_speakers'):
        assert any(m['sender_id']=='provider-a' for call in calls for m in json.loads(call.messages[-1].content)['messages'])
    if case['expect'].get('updated_contacts'):
        assert sorted(c.contact_id for c in op.report.contacts if c.analysis_outcome=='updated')==case['expect']['updated_contacts']
    if case['expect'].get('blocked_contacts'):
        assert sorted(c.contact_id for c in op.report.contacts if c.reason=='source_not_complete')==case['expect']['blocked_contacts']
    if case['expect'].get('operation_count'):
        assert conn.execute('SELECT COUNT(*) FROM operations WHERE account_id=?',(account,)).fetchone()[0]==case['expect']['operation_count']
    if case['expect'].get('message_reads')==0:assert not source.calls
    if case['expect'].get('no_cross_contact_evidence'):
        assert conn.execute("SELECT COUNT(*) FROM contacts WHERE account_id=? AND remark='兴🌟'",(account,)).fetchone()[0]==2
        for call in calls:
            if isinstance(call,str):continue
            data=json.loads(call.messages[-1].content)
            assert data['contact_id']==contact
            assert all(m['conversation_id'] in case['expect']['model_target_rooms'] for m in data['messages'])
    return dict(source_outcome=op.report.source_outcome if op.report else 'stopped',analysis_outcome=op.report.analysis_outcome if op.report else 'stopped',model_calls=len(calls),publish=after>before,operation=op,source=source,services=services,given=g,calls=calls)
