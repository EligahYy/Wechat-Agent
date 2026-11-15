import {useState} from 'react';
import {Dialog} from '../../components/Dialog';
import {FormField} from '../../components/FormField';
import {request,ApiError,messageFor} from '../../api/client';
import type {ContactKey} from '../../api/types';
import {groups,tags,endpoint,type Profile} from './types';
export function ProfileEditor({profile,group,contact,onClose,onSaved}:{profile:Profile;group:string;contact:ContactKey;onClose:()=>void;onSaved:()=>void}){
 const title=group==='goods'?'货品资料':group==='logistics'?'物流资料':'沟通情况';
 const values=(p:Profile)=>Object.fromEntries(Object.keys(groups[group]).map(name=>{const value=group==='communication'?p.effective.communication[name as keyof Profile['effective']['communication']]:p.effective[group as 'goods'|'logistics'][name];return [name,Array.isArray(value)?value.join('、'):typeof value==='object'&&value?value.value||'':value||''];}));
 const initial=values(profile);const [base,setBase]=useState(profile),[fields,setFields]=useState<Record<string,string>>(initial),[note,setNote]=useState(profile.manual.notes[group]||''),[restored,setRestored]=useState<string[]>([]),[error,setError]=useState(''),[conflict,setConflict]=useState(false),[busy,setBusy]=useState(false);
 const baseline=values(base),dirty=restored.length>0||Object.keys(fields).some(name=>fields[name]!==baseline[name])||note!==(base.manual.notes[group]||'');
 const save=async()=>{setBusy(true);setError('');try{
  const patch:Record<string,string|string[]|null>={};for(const name of Object.keys(fields)){if(restored.includes(name))patch[`${group}.${name}`]=null;else if(fields[name]!==baseline[name])patch[`${group}.${name}`]=name==='tags'?fields[name].split(/[、,，\n]/).map(s=>s.trim()).filter(Boolean):fields[name].trim()||null;}
  await request(endpoint(contact,'manual'),{method:'PATCH',body:JSON.stringify({account_id:contact.account_id,expected_version:base.manual_version,fields:patch,notes:group==='communication'?{}:{[group]:note||null}})});onSaved();onClose();
 }catch(reason){setConflict(reason instanceof ApiError&&reason.status===409);setError(reason instanceof ApiError&&reason.status===409?'资料已变化，填写内容已保留，请核对最新版本后再保存。':messageFor(reason));}finally{setBusy(false);}};
 const reconcile=async()=>{setBusy(true);try{const latest=await request<Profile>(`${endpoint(contact)}?${new URLSearchParams({account_id:contact.account_id})}`);const next=values(latest);setFields(previous=>Object.fromEntries(Object.keys(previous).map(name=>[name,previous[name]===baseline[name]?next[name]:previous[name]])));if(note===(base.manual.notes[group]||''))setNote(latest.manual.notes[group]||'');setBase(latest);setConflict(false);setError('');}catch(reason){setError(messageFor(reason));}finally{setBusy(false);}};
 return <Dialog open title={`编辑${title}`} onClose={()=>{if(!busy)onClose();}} footer={<><button className="button secondary" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={!dirty||busy||conflict} onClick={()=>void save()}>保存资料</button></>}>
  <div className="profile-editor">
   {error&&<div className="error-banner" role="alert">{error}{conflict&&<button className="text-button" disabled={busy} onClick={()=>void reconcile()}>保留填写并核对最新版本</button>}</div>}
   {Object.entries(groups[group]).map(([name,label])=><div key={name}><FormField label={label} multiline value={fields[name]} disabled={busy||restored.includes(name)} onChange={event=>setFields({...fields,[name]:event.target.value})}/>{base.manual.fields[`${group}.${name}`]!==undefined&&<button className="text-button" disabled={busy} onClick={()=>setRestored(previous=>previous.includes(name)?previous.filter(item=>item!==name):[...previous,name])}>{restored.includes(name)?`保留 ${label} 人工值`:`恢复 ${label} 模型值`}</button>}</div>)}
   {group==='communication'?<p className="field-hint">标签可用：{tags.join('、')}。多个标签用顿号分隔；业务时间请填写带时区的ISO时间，例如2026-11-15T09:00:00+08:00。</p>:<FormField label={group==='goods'?'货品补充资料':'物流补充资料'} multiline value={note} disabled={busy} onChange={event=>setNote(event.target.value)}/>}
   <p className="field-hint">人工资料优先展示。恢复模型值会清除对应人工覆盖；不会删除聊天原文。</p>
  </div>
 </Dialog>;
}
