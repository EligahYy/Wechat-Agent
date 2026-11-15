import {useEffect,useState} from 'react';
import {FileText} from 'lucide-react';
import {request,messageFor} from '../../api/client';
import type {ContactKey} from '../../api/types';
import {ProfileOverview} from './ProfileOverview';
import {ProfileEditor} from './ProfileEditor';
import {ShipmentList} from './ShipmentList';
import {EvidencePanel} from './EvidencePanel';
import {endpoint,type Profile,type SourceRef} from './types';
export function ProfileDialog({contact,revision,visible,view,onChanged}:{contact:ContactKey;revision:number;visible:boolean;view:string;onChanged:()=>void}){
 const [data,setData]=useState<Profile|null>(null),[error,setError]=useState(''),[reload,setReload]=useState(0),[editing,setEditing]=useState(''),[evidence,setEvidence]=useState<SourceRef[]|null>(null);
 useEffect(()=>{if(!visible)return;const controller=new AbortController();setError('');request<Profile>(`${endpoint(contact)}?${new URLSearchParams({account_id:contact.account_id})}`,{signal:controller.signal}).then(value=>{if(!controller.signal.aborted)setData(value);}).catch(reason=>{if(!controller.signal.aborted)setError(messageFor(reason));});return()=>controller.abort();},[contact.account_id,contact.contact_id,revision,reload,visible]);
 const changed=()=>{setReload(value=>value+1);onChanged();};
 return <>{error&&<div className="error-banner" role="alert">{error}<button className="text-button" onClick={()=>setReload(value=>value+1)}>重试资料</button></div>}{!data&&!error?<p role="status">正在读取客户资料…</p>:data&&<>{!data.model&&view==='overview'&&<div className="profile-empty"><FileText size={24}/><strong>档案尚未生成</strong><span>可先补充人工资料，再同步并整理此客户。</span></div>}{(data.pending||data.model&&!data.complete)&&<p className="field-hint">{data.pending?'资料待更新，保留上次结果与人工修改。':'整理不完整，已保留有依据的资料。'}</p>}{view==='shipments'?<ShipmentList shipments={data.shipments} contact={contact} onSaved={changed} onEvidence={setEvidence}/>:<ProfileOverview profile={data} onEdit={setEditing} onEvidence={setEvidence}/>} {editing&&<ProfileEditor profile={data} group={editing} contact={contact} onClose={()=>setEditing('')} onSaved={changed}/>} {evidence&&<EvidencePanel contact={contact} refs={evidence} onClose={()=>setEvidence(null)}/>}</>}</>;
}
