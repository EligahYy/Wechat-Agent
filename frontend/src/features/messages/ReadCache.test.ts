import {describe,it,expect} from 'vitest';
import {ReadCache} from './ReadCache';
describe('bounded archive read cache',()=>{
 it('expires entries without allowing cache reads to extend freshness',()=>{
  const cache=new ReadCache<string>();cache.set('account:person:day','value',0);
  expect(cache.get('account:person:day',29_999)).toBe('value');cache.update('account:person:day','local navigation');expect(cache.get('account:person:day',30_000)).toBeUndefined();
 });
 it('evicts least recently accessed scope and can clear after revision changes',()=>{
  const cache=new ReadCache<number>(2);cache.set('a',1,0);cache.set('b',2,0);cache.get('a',1);cache.set('c',3,1);
  expect(cache.get('b',2)).toBeUndefined();expect(cache.get('a',2)).toBe(1);cache.clear();expect(cache.get('a',3)).toBeUndefined();
 });
});
