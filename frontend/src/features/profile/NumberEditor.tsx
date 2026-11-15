import {useState} from 'react';
import {Dialog} from '../../components/Dialog';
import {FormField} from '../../components/FormField';
import {request,ApiError,messageFor} from '../../api/client';
import type {ContactKey} from '../../api/types';
import {endpoint,type Profile,type Shipment} from './types';
export function NumberEditor({shipment,contact,onClose,onSaved}:{shipment:Shipment;contact:ContactKey;onClose:()=>void;onSaved:()=>void}){
 const [base,setBase]=useState(shipment),[value,setValue]=useState(shipment.numbers.join('\n')),[error,setError]=useState(''),[busy,setBusy]=useState(false),[conflict,setConflict]=useState(false);
 const save=async()=>{setBusy(true);setError('');try{await request(`/api/shipments/${encodeURIComponent(base.shipment_id)}/numbers`,{method:'PATCH',body:JSON.stringify({...contact,expected_version:base.version,numbers:value.split('\n').map(s=>s.trim()).filter(Boolean)})});onSaved();onClose();}catch(reason){setConflict(reason instanceof ApiError&&reason.status===409);setError(reason instanceof ApiError&&reason.status===409?'备货记录已变化，单号填写已保留，请核对最新版本。':messageFor(reason));}finally{setBusy(false);}};
 const reconcile=async()=>{setBusy(true);try{const latest=await request<Profile>(`${endpoint(contact)}?${new URLSearchParams({account_id:contact.account_id})}`);const found=latest.shipments.find(row=>row.shipment_id===base.shipment_id);if(!found)throw Error('shipment_missing');setBase(found);setConflict(false);setError('');}catch(reason){setError(messageFor(reason));}finally{setBusy(false);}};
 return <Dialog open title="编辑单号" onClose={()=>{if(!busy)onClose();}} footer={<><button className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy||conflict||value===base.numbers.join('\n')} onClick={()=>void save()}>保存单号</button></>}>
  <FormField label="单号（每行一个）" multiline value={value} disabled={busy} onChange={event=>setValue(event.target.value)}/><p className="field-hint">自动去重，留空清除。录入单号不会改变备货进度。</p>{conflict&&<p className="field-hint">当前服务端进度：{base.stage}；已有单号：{base.numbers.join('、')||'无'}</p>}{error&&<div className="error-banner" role="alert">{error}{conflict&&<button className="text-button" onClick={()=>void reconcile()}>保留填写并核对最新版本</button>}</div>}
 </Dialog>;
}
