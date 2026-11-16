import {act, renderHook, waitFor} from '@testing-library/react';
import {beforeEach, expect, it, vi} from 'vitest';
import {request} from '../api/client';
import {useOperations} from './useOperations';
import type {Operation} from '../api/types';
vi.mock('../api/client',async importOriginal=>({...await importOriginal<typeof import('../api/client')>(),request:vi.fn()}));
const old:Operation={id:'old',scope:{account_id:'acct-1',contact_id:'merchant-a'},action:'sync_and_organize',state:'succeeded',source_state:'succeeded',phase:'completed',counts:{},remaining:0,error_code:null,available_actions:[],created_at:'2026-11-16T10:00:00Z',updated_at:'2026-11-16T10:00:00Z',history_complete:false};
const latest:Operation={...old,id:'latest',created_at:'2026-11-16T12:00:00Z',updated_at:'2026-11-16T12:01:00Z'};
beforeEach(()=>vi.mocked(request).mockReset());
it('retains a newly submitted record when a stale list is loaded again',async()=>{
 vi.mocked(request).mockImplementation(async(_url,options)=>options?.method==='POST'?latest:{items:[old]});
 const {result}=renderHook(()=>useOperations('acct-1',vi.fn()));
 await waitFor(()=>expect(result.current.history).toHaveLength(1));
 await act(async()=>{await result.current.start('merchant-a');});
 await waitFor(()=>expect(result.current.history.map(o=>o.id)).toEqual(['latest','old']));
 await act(async()=>{await result.current.loadHistory();});
 expect(result.current.history.map(o=>o.id)).toEqual(['latest','old']);
});
it('updates the cached history entry when polling reaches a terminal result',async()=>{
 const running={...latest,state:'running',phase:'source',report:null} as Operation;
 vi.mocked(request).mockImplementation(async(url,options)=>options?.method==='POST'?running:String(url).includes('/latest?')?latest:{items:[old]});
 const done=vi.fn();const {result}=renderHook(()=>useOperations('acct-1',done));
 await waitFor(()=>expect(result.current.history).toHaveLength(1));
 await act(async()=>{await result.current.start('merchant-a');});
 await waitFor(()=>expect(done).toHaveBeenCalledOnce());
 expect(result.current.history.find(o=>o.id==='latest')?.state).toBe('succeeded');
});
it('remembers detail records and never downgrades a newer cached outcome',async()=>{
 vi.mocked(request).mockImplementation(async url=>String(url).includes('/latest?')?latest:{items:[old,{...latest,state:'running',updated_at:'2026-11-16T12:00:00Z'}]});
 const {result}=renderHook(()=>useOperations('acct-1',vi.fn()));
 await waitFor(()=>expect(result.current.history).toHaveLength(2));
 await act(async()=>{await result.current.read('latest');});
 await act(async()=>{await result.current.loadHistory();});
 expect(result.current.history[0].state).toBe('succeeded');
 expect(result.current.history.map(o=>o.id)).toEqual(['latest','old']);
});
it('ignores an old account list response after switching accounts',async()=>{
 let resolveOld!:(value:unknown)=>void;
 vi.mocked(request).mockImplementation(async url=>String(url).includes('acct-1')?new Promise(resolve=>{resolveOld=resolve;}):{items:[{...latest,scope:{account_id:'acct-2',contact_id:'merchant-b'}}]});
 const done=vi.fn();const {result,rerender}=renderHook(({account})=>useOperations(account,done),{initialProps:{account:'acct-1'}});
 await waitFor(()=>expect(resolveOld).toBeDefined());
 rerender({account:'acct-2'});
 await waitFor(()=>expect(result.current.history[0]?.scope.account_id).toBe('acct-2'));
 await act(async()=>{resolveOld({items:[old]});});
 expect(result.current.history).toHaveLength(1);
 expect(result.current.history[0].scope.account_id).toBe('acct-2');
});

it('preserves server ordering for legacy records without creation timestamps',async()=>{
 const first={...old,created_at:undefined,id:'first',updated_at:'2026-11-16T10:00:00Z'};
 const second={...old,created_at:undefined,id:'second',updated_at:'2026-11-16T12:00:00Z'};
 vi.mocked(request).mockResolvedValue({items:[first,second]});
 const {result}=renderHook(()=>useOperations('acct-1',vi.fn()));
 await waitFor(()=>expect(result.current.history).toHaveLength(2));
 expect(result.current.history.map(o=>o.id)).toEqual(['first','second']);
});
