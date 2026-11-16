import type {ReactNode} from 'react';
import {ChevronRight} from 'lucide-react';
import type {Operation} from '../api/types';
import {historyScopeLabel,presentOperation} from '../app/operationOutcome';
import {operationTitle} from '../app/useOperations';
export function OperationHistory({operations,selectedId,onSelect,detail}:{operations:Operation[];selectedId?:string;onSelect:(operation:Operation)=>void;detail:ReactNode}){
 return <div className="history-list">{operations.map(item=><div className="history-record" data-tone={presentOperation(item).tone} key={item.id}><button className="history-entry" aria-expanded={selectedId===item.id} aria-controls={selectedId===item.id?`record-${item.id}`:undefined} onClick={()=>onSelect(item)}><div><strong>{historyScopeLabel(item,operations)} · {operationTitle(item)}</strong><p>{new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'medium',timeStyle:'short'}).format(new Date(item.created_at||item.updated_at))}</p></div><ChevronRight size={18}/></button>{selectedId===item.id&&detail}</div>)}</div>;
}
