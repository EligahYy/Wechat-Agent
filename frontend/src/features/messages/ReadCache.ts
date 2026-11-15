/** Component-owned LRU; local navigation must not renew archive freshness. */
export class ReadCache<T> {
 private entries=new Map<string,{value:T;expires:number}>();
 constructor(private limit=6,private ttlMs=30_000){}
 get(key:string,now=Date.now()):T|undefined {
  const entry=this.entries.get(key);if(!entry)return;
  if(entry.expires<=now){this.entries.delete(key);return;}
  this.entries.delete(key);this.entries.set(key,entry);return entry.value;
 }
 set(key:string,value:T,now=Date.now()){
  this.entries.delete(key);this.entries.set(key,{value,expires:now+this.ttlMs});
  while(this.entries.size>this.limit)this.entries.delete(this.entries.keys().next().value!);
 }
 update(key:string,value:T){const entry=this.entries.get(key);if(entry)entry.value=value;}
 clear(){this.entries.clear();}
}
