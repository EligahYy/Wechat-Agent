import {describe,it,expect} from 'vitest';
import {presentOperation} from './operationOutcome';
import type {Operation} from '../api/types';
const operation=(overrides:Partial<Operation>={}):Operation=>({id:'o',scope:{account_id:'a',contact_id:'p'},action:'sync_and_organize',state:'succeeded',source_state:'succeeded',phase:'completed',counts:{},remaining:0,error_code:null,available_actions:[],updated_at:'2026-11-16T00:00:00Z',history_complete:false,...overrides});
describe('durable outcome presentation',()=>{
 it('does not infer legacy success from three completed conversations',()=>{expect(presentOperation(operation({state:'failed',counts:{completed_conversations:3,conversations_total:3}})).title).toBeNull();});
 it('uses a name snapshot without requiring loaded contacts',()=>{expect(presentOperation(operation({contact_name_snapshot:'<兴🌟>'})).scopeLabel).toBe('<兴🌟>');});
 it('keeps a warning distinct from model failure and selects its action',()=>{
 const o=operation({report:{version:1,scope_label:'兴',source_outcome:'completed',analysis_outcome:'failed',contacts:[],issues:[{code:'source_group_membership_unverified',severity:'warning',stage:'metadata',scope:'operation',suggested_action:'none'},{code:'model_budget_unverified',severity:'blocker',stage:'model',scope:'operation',suggested_action:'open_model_settings'}]}});
 const p=presentOperation(o);expect(p.title).toBe('消息已同步，整理未完成');expect(p.action).toBe('open_model_settings');expect(p.issues[0].severity).toBe('blocker');
 });
});

it('distinguishes same-name records including identifiers with a shared suffix',async()=>{
 const {historyScopeLabel}=await import('./operationOutcome');
 const first=operation({contact_name_snapshot:'刘',scope:{account_id:'a',contact_id:'123456789@openim'}});
 const second=operation({contact_name_snapshot:'刘',scope:{account_id:'a',contact_id:'987654321@openim'}});
 expect(historyScopeLabel(first,[first,second])).not.toBe(historyScopeLabel(second,[first,second]));
 expect(historyScopeLabel(first,[first,first])).toBe('刘');
});
